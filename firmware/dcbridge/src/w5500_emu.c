#include <string.h>
#include "w5500_emu.h"
#include "ring.h"   // DCB_BARRIER

// Common register offsets
#define MR        0x00
#define SHAR      0x09
#define RTR       0x19
#define RCR       0x1B
#define PHYCFGR   0x2E
#define VERSIONR  0x39
// Socket register offsets
#define Sn_MR       0x00
#define Sn_CR       0x01
#define Sn_IR       0x02
#define Sn_SR       0x03
#define Sn_TTL      0x16
#define Sn_RXBUF    0x1E
#define Sn_TXBUF    0x1F
#define Sn_TX_FSR   0x20
#define Sn_TX_RD    0x22
#define Sn_TX_WR    0x24
#define Sn_RX_RSR   0x26
#define Sn_RX_RD    0x28
#define Sn_RX_WR    0x2A
#define Sn_IMR      0x2C
#define Sn_FRAG     0x2D

#define CR_OPEN  0x01
#define CR_CLOSE 0x10
#define CR_SEND  0x20
#define CR_RECV  0x40
#define SOCK_CLOSED 0x00
#define SOCK_MACRAW 0x42
#define IR_SENDOK   0x10
#define IR_RECV     0x04

static inline uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] << 8 | p[1]); }
static inline void wr16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)(v >> 8); p[1] = (uint8_t)v; }

static void reset_registers(w5500_t *w) {
    memset(w->common, 0, sizeof w->common);
    memset(w->sock, 0, sizeof w->sock);
    wr16(&w->common[RTR], 0x07D0);
    w->common[RCR] = 8;
    w->common[VERSIONR] = W5500_VERSION;
    w->phy_user = 0xB8;
    for (int n = 0; n < 8; n++) {
        uint8_t *s = w->sock[n];
        s[Sn_TTL] = 0x80;
        s[Sn_RXBUF] = 2;
        s[Sn_TXBUF] = 2;
        s[Sn_IMR] = 0xFF;
        wr16(&s[Sn_FRAG], 0x4000);
    }
    w->send_ptr = 0;
    w->sock_open = false;
    w->rx_rd_committed = 0;
    DCB_BARRIER();
    w->reset_req++;                  // core0 zeroes tx_rd / rx_wr / drains queue
    w->st_resets++;
    w5500_refresh(w);
}

void w5500_init(w5500_t *w) {
    memset(w, 0, sizeof *w);
    for (int bsb = 0; bsb < 32; bsb++) {
        int n = bsb >> 2;
        switch (bsb & 3) {
        case 0: w->base[bsb] = bsb ? w->sink : w->common; w->mask[bsb] = bsb ? 0 : 63; break;
        case 1: w->base[bsb] = w->sock[n]; w->mask[bsb] = 63; break;
        case 2: w->base[bsb] = n ? w->sink : w->txbuf; w->mask[bsb] = n ? 0 : W5500_BUF_MASK; break;
        case 3: w->base[bsb] = n ? w->sink : w->rxbuf; w->mask[bsb] = n ? 0 : W5500_BUF_MASK; break;
        }
    }
    reset_registers(w);
}

// --------------------------------------------------------------------------
// Socket commands (only socket 0 / MACRAW is functional, which is all KOS uses)
// --------------------------------------------------------------------------
static void exec_cmd(w5500_t *w, int n, uint8_t cmd) {
    uint8_t *s = w->sock[n];
    w->st_cmds++;
    if (n != 0) return;
    switch (cmd) {
    case CR_OPEN:
        if ((s[Sn_MR] & 0x0F) == 0x04) {
            wr16(&s[Sn_TX_WR], 0);
            wr16(&s[Sn_RX_RD], 0);
            w->send_ptr = 0;
            w->rx_rd_committed = 0;
            w->mac_filter = (s[Sn_MR] & 0x80) != 0;
            DCB_BARRIER();
            w->reset_req++;
            w->sock_open = true;
            s[Sn_SR] = SOCK_MACRAW;
        } else {
            s[Sn_SR] = SOCK_CLOSED;   // TCP/UDP offload is not emulated
        }
        break;
    case CR_CLOSE:
        w->sock_open = false;
        s[Sn_SR] = SOCK_CLOSED;
        break;
    case CR_SEND: {
        uint16_t wr = rd16(&s[Sn_TX_WR]);
        uint16_t len = (uint16_t)(wr - w->send_ptr);
        uint32_t h = w->sendq_head;
        if (len == 0) break;
        if (w->sock_open && len <= W5500_MAX_FRAME && h - w->sendq_tail < W5500_SENDQ_LEN) {
            w->sendq[h & (W5500_SENDQ_LEN - 1)] = (w5500_send_t){ w->send_ptr, len };
            DCB_BARRIER();
            w->sendq_head = h + 1;
        } else {
            w->st_drop_tx++;   // tx_rd catches up with the next delivered frame
        }
        w->send_ptr = wr;
        break;
    }
    case CR_RECV:
        w->rx_rd_committed = rd16(&s[Sn_RX_RD]);
        break;
    default:
        break;
    }
    s[Sn_CR] = 0;   // command accepted immediately
}

static void write_byte(w5500_t *w, uint8_t bsb, uint16_t addr, uint8_t v) {
    uint8_t kind = bsb & 3;
    if (bsb == 0) {
        uint8_t a = (uint8_t)addr;
        if (addr > 0x3F) return;
        if (a == MR) {
            if (v & 0x80) { reset_registers(w); return; }
            w->common[MR] = v;
        } else if (a == PHYCFGR) {
            w->phy_user = v & 0xF8;
            w5500_refresh(w);
        } else if (a != VERSIONR && a < 0x3A) {
            w->common[a] = v;
        }
    } else if (kind == 1) {
        int n = bsb >> 2;
        uint8_t a = (uint8_t)addr;
        if (addr > 0x3F) return;
        switch (a) {
        case Sn_CR: exec_cmd(w, n, v); break;
        case Sn_IR: w->sock[n][Sn_IR] &= (uint8_t)~v; break;
        case Sn_SR:
        case Sn_TX_FSR: case Sn_TX_FSR + 1:
        case Sn_TX_RD:  case Sn_TX_RD + 1:
        case Sn_RX_RSR: case Sn_RX_RSR + 1:
        case Sn_RX_WR:  case Sn_RX_WR + 1:
            break;                       // read-only
        default: w->sock[n][a] = v; break;
        }
    } else if (kind != 0) {
        w->base[bsb][addr & w->mask[bsb]] = v;   // TX/RX buffer (or sink)
    }
}

// --------------------------------------------------------------------------
// Hot path. KOS frames: [addr hi][addr lo][ctrl] then data in VDM mode until
// /CS rises. Note w5500_exec_cmd() in KOS keeps /CS low after writing Sn_CR and
// clocks another "header" + a status read; a real W5500 treats all of that as
// VDM write data (Sn_IR, Sn_SR, Sn_PORT...) and returns 0x00 on MISO, which is
// what ends KOS's poll loop. We reproduce that exactly: during writes MISO is
// the PIO filler (0x00) and the bytes are continued writes.
// --------------------------------------------------------------------------
int DCB_RAMFUNC(w5500_on_byte)(w5500_t *w, uint8_t in, uint8_t out[2]) {
    switch (w->state) {
    case 0: w->addr = (uint16_t)(in << 8); w->state = 1; return 0;
    case 1: w->addr |= in;                 w->state = 2; return 0;
    case 2: {
        uint8_t bsb = in >> 3;
        w->bsb = bsb;
        if (in & 0x04) { w->state = 3; return 0; }   // write
        w->state = 4;                                 // read: deadline starts now
        const uint8_t *b = w->base[bsb];
        uint16_t m = w->mask[bsb], a = w->addr;
        out[0] = b[a & m];
        out[1] = b[(uint16_t)(a + 1) & m];
        w->addr = (uint16_t)(a + 2);
        return 2;
    }
    case 3:
        write_byte(w, w->bsb, w->addr, in);
        w->addr++;
        return 0;
    default:  // 4: read continues, keep two bytes queued ahead
        out[0] = w->base[w->bsb][w->addr & w->mask[w->bsb]];
        w->addr++;
        return 1;
    }
}

void DCB_RAMFUNC(w5500_refresh)(w5500_t *w) {
    uint8_t *s = w->sock[0];
    bool pending_reset = w->reset_req != w->reset_ack;
    uint16_t tx_rd = pending_reset ? 0 : w->tx_rd;
    uint16_t rx_wr = pending_reset ? 0 : w->rx_wr;
    uint16_t used = (uint16_t)(rd16(&s[Sn_TX_WR]) - tx_rd);
    uint16_t fsr = used > W5500_BUF_SIZE ? 0 : (uint16_t)(W5500_BUF_SIZE - used);
    uint16_t rsr = (uint16_t)(rx_wr - w->rx_rd_committed);

    wr16(&s[Sn_TX_FSR], fsr);
    wr16(&s[Sn_TX_RD], tx_rd);
    wr16(&s[Sn_RX_RSR], rsr);
    wr16(&s[Sn_RX_WR], rx_wr);
    if (rsr) s[Sn_IR] |= IR_RECV;
    uint32_t ok = w->sendok_count;
    if (ok != w->sendok_seen) { w->sendok_seen = ok; s[Sn_IR] |= IR_SENDOK; }
    // PHYCFGR: bit0 LNK, bit1 SPD(100M), bit2 DPX(full)
    w->common[PHYCFGR] = (uint8_t)(w->phy_user | (w->link_up ? 0x07 : 0x00));
}

// --------------------------------------------------------------------------
// core0 side
// --------------------------------------------------------------------------
void w5500_core0_service(w5500_t *w) {
    uint32_t req = w->reset_req;
    if (req != w->reset_ack) {
        w->tx_rd = 0;
        w->rx_wr = 0;
        w->sendq_tail = w->sendq_head;
        DCB_BARRIER();
        w->reset_ack = req;
    }
}

bool w5500_tx_pop(w5500_t *w, uint8_t *dst, uint16_t *len) {
    w5500_core0_service(w);
    uint32_t t = w->sendq_tail;
    if (t == w->sendq_head) return false;
    DCB_BARRIER();
    w5500_send_t e = w->sendq[t & (W5500_SENDQ_LEN - 1)];
    for (uint16_t i = 0; i < e.len; i++)
        dst[i] = w->txbuf[(uint16_t)(e.start + i) & W5500_BUF_MASK];
    *len = e.len;
    DCB_BARRIER();
    w->tx_rd = (uint16_t)(e.start + e.len);
    w->sendq_tail = t + 1;
    w->sendok_count++;
    w->st_frames_tx++;
    return true;
}

bool w5500_rx_push(w5500_t *w, const uint8_t *f, uint16_t len) {
    w5500_core0_service(w);
    uint32_t req = w->reset_req;
    if (!w->sock_open || len < 14 || len > W5500_MAX_FRAME) return true;   // drop
    if (w->mac_filter && !(f[0] & 0x01) && memcmp(f, &w->common[SHAR], 6) != 0) {
        w->st_drop_rx_filter++;
        return true;
    }
    uint16_t need = (uint16_t)(len + 2);
    uint16_t used = (uint16_t)(w->rx_wr - w->rx_rd_committed);
    if (W5500_BUF_SIZE - used < need) { w->st_drop_rx_full++; return false; }

    uint16_t p = w->rx_wr;
    w->rxbuf[p++ & W5500_BUF_MASK] = (uint8_t)(need >> 8);   // MACRAW header: length incl. itself
    w->rxbuf[p++ & W5500_BUF_MASK] = (uint8_t)need;
    for (uint16_t i = 0; i < len; i++) w->rxbuf[p++ & W5500_BUF_MASK] = f[i];
    DCB_BARRIER();
    if (w->reset_req != req) return true;    // socket was reset meanwhile: discard
    w->rx_wr = p;
    w->st_frames_rx++;
    return true;
}
