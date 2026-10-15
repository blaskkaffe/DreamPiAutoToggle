#include <string.h>
#include "sd_link.h"

sd_link_stats_t sd_link_stats;

static sd_emu_t *E;
static const sd_link_io_t *IO;
static bool was_connected;
static uint32_t w_sent;              // absolute index of the next write slot to send
static uint32_t session_sent;        // session id we last announced
static uint32_t session_sent_ms;

// Outstanding read requests, to avoid asking twice for the same sectors.
#define OUTSTANDING 64
static struct { uint32_t lba; uint32_t t; } outst[OUTSTANDING];
static uint32_t outst_i;

// ---------------------------------------------------------------------------
static inline void le16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static inline void le32(uint8_t *p, uint32_t v) { le16(p, (uint16_t)v); le16(p + 2, (uint16_t)(v >> 16)); }
static inline uint32_t rd32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static bool send(uint8_t type, const uint8_t *a, uint16_t alen, const uint8_t *b, uint16_t blen) {
    uint8_t h[SDL_HDR] = { 0xD5, 0xC3, type, 0x00 };
    le16(&h[4], (uint16_t)(alen + blen));
    if (IO->room() < (uint32_t)SDL_HDR + alen + blen) return false;   // whole frames only
    IO->write(h, SDL_HDR);
    if (alen) IO->write(a, alen);
    if (blen) IO->write(b, blen);
    sd_link_stats.frames_tx++;
    return true;
}

void sd_link_init(sd_emu_t *e, const sd_link_io_t *io) {
    E = e;
    IO = io;
    for (int i = 0; i < OUTSTANDING; i++) outst[i].lba = SD_LBA_NONE;
}

// ---------------------------------------------------------------------------
// Receive path
// ---------------------------------------------------------------------------
static uint8_t  rx[SDL_HDR + 8 + SD_SECTOR];
static uint32_t rx_n;

static void on_frame(uint8_t type, const uint8_t *p, uint16_t len) {
    sd_link_stats.frames_rx++;
    sd_link_stats.daemon_seen = true;
    switch (type) {
    case SDL_READY:
        if (len >= 12) sd_be_session_ready(E, rd32(p), rd32(p + 4), rd32(p + 8) & 1);
        break;
    case SDL_DATA:
        if (len >= 4 + SD_SECTOR) {
            uint32_t lba = rd32(p);
            sd_be_cache_put(E, lba, p + 4);
            for (int i = 0; i < OUTSTANDING; i++)
                if (outst[i].lba == lba) outst[i].lba = SD_LBA_NONE;
        }
        break;
    case SDL_WACK:
        // Acks arrive in order; the daemon writes each sector before acking.
        sd_be_write_acked(E);
        break;
    default:
        break;
    }
}

void sd_link_rx(const uint8_t *p, uint32_t n) {
    while (n--) {
        uint8_t b = *p++;
        if (rx_n == 0 && b != 0xD5) { sd_link_stats.resyncs++; continue; }
        if (rx_n == 1 && b != 0xC3) { rx_n = (b == 0xD5); sd_link_stats.resyncs++; continue; }
        rx[rx_n++] = b;
        if (rx_n < SDL_HDR) continue;
        uint16_t len = (uint16_t)(rx[4] | rx[5] << 8);
        if (len > sizeof rx - SDL_HDR) { rx_n = 0; sd_link_stats.resyncs++; continue; }
        if (rx_n == (uint32_t)SDL_HDR + len) {
            on_frame(rx[2], &rx[SDL_HDR], len);
            rx_n = 0;
        }
    }
}

// ---------------------------------------------------------------------------
// Transmit path
// ---------------------------------------------------------------------------
static bool outstanding(uint32_t lba, uint32_t now) {
    for (int i = 0; i < OUTSTANDING; i++)
        if (outst[i].lba == lba && now - outst[i].t < 40) return true;
    return false;
}

static void mark_outstanding(uint32_t lba, uint32_t now) {
    outst[outst_i].lba = lba;
    outst[outst_i].t = now;
    outst_i = (outst_i + 1) % OUTSTANDING;
}

void sd_link_service(uint32_t now, bool connected) {
    if (!connected) { was_connected = false; return; }
    if (!was_connected) {
        // (Re)connected: the daemon knows nothing. Re-announce everything
        // that is still in flight.
        was_connected = true;
        sd_link_stats.daemon_seen = false;
        w_sent = E->w_tail;
        session_sent = E->session_ready;
        for (int i = 0; i < OUTSTANDING; i++) outst[i].lba = SD_LBA_NONE;
        uint8_t p[4];
        le16(p, SDL_PROTO_VERSION);
        le16(p + 2, SD_CACHE_N);
        send(SDL_HELLO, p, 4, NULL, 0);
    }

    // 1. Writes, in order. They go first so the daemon applies them before
    //    anything that follows (a session start or a read of the same sector).
    while (w_sent != E->w_head) {
        const sd_wslot_t *s = sd_be_write_slot(E, w_sent);
        uint8_t p[4];
        le32(p, s->lba);
        if (!send(SDL_WRITE, p, 4, s->data, SD_SECTOR)) break;
        w_sent++;
        sd_link_stats.writes_sent++;
    }

    // 2. Session start (CMD0). Re-sent if the daemon does not answer.
    uint32_t req = E->session_req;
    if (req != E->session_ready &&
        (req != session_sent || now - session_sent_ms > 1000)) {
        uint8_t p[8];
        le32(p, req);
        le32(p + 4, E->session_idle_ms);
        if (send(SDL_SESSION, p, 8, NULL, 0)) { session_sent = req; session_sent_ms = now; }
    }

    // 3. Reads
    while (IO->room() >= SDL_HDR + 6) {
        uint32_t lba;
        if (!sd_be_pop_request(E, &lba)) break;
        if (sd_be_cached(E, lba) || outstanding(lba, now)) continue;
        uint8_t p[6];
        le32(p, lba);
        le16(p + 4, SD_PREFETCH);
        if (!send(SDL_READ, p, 6, NULL, 0)) break;
        for (uint32_t i = 0; i < SD_PREFETCH; i++) mark_outstanding(lba + i, now);
        sd_link_stats.reads_sent++;
    }
    IO->flush();
}
