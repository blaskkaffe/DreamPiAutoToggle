// Host test: replays the KallistiOS w5500_adapter.c SPI sequences byte-by-byte
// against the emulator, with a model of the PIO MISO FIFO (filler 0x00 when
// empty, flushed on /CS rise). Build: cc -O2 -I../src test_w5500.c ../src/w5500_emu.c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include "w5500_emu.h"

static w5500_t W;
static uint8_t fifo[8]; static int fifo_n;
static int cs_low;

static uint8_t xfer(uint8_t mosi) {
    assert(cs_low);
    uint8_t miso = 0x00;
    if (fifo_n) { miso = fifo[0]; memmove(fifo, fifo + 1, --fifo_n); }
    uint8_t out[2];
    int n = w5500_on_byte(&W, mosi, out);
    for (int i = 0; i < n; i++) { assert(fifo_n < 4); fifo[fifo_n++] = out[i]; }
    return miso;
}
static void set_cs(int enabled) {   // KOS spi_set_cs(true) == assert
    if (enabled) { cs_low = 1; }
    else { cs_low = 0; fifo_n = 0; w5500_frame_start(&W); w5500_refresh(&W); }
}
static void write_data(const uint8_t *d, size_t n) { while (n--) xfer(*d++); }
static uint8_t read_byte(void) { return xfer(0xFF); }
static void read_data(uint8_t *d, size_t n) { while (n--) *d++ = xfer(0xFF); }

// ---- faithful ports of the KOS driver helpers ----
#define WRITE (1 << 2)
static uint8_t read_reg(uint8_t blk, uint16_t a) {
    uint8_t c[3] = { a >> 8, a, (uint8_t)(blk << 3) };
    set_cs(1); write_data(c, 3); uint8_t r = read_byte(); set_cs(0); return r;
}
static void write_reg(uint8_t blk, uint16_t a, uint8_t v) {
    uint8_t c[4] = { a >> 8, a, (uint8_t)(blk << 3 | WRITE), v };
    set_cs(1); write_data(c, 4); set_cs(0);
}
static uint16_t read_reg16(uint8_t blk, uint16_t a) {
    uint8_t c[3] = { a >> 8, a, (uint8_t)(blk << 3) }, d[2];
    set_cs(1); write_data(c, 3); read_data(d, 2); set_cs(0); return d[0] << 8 | d[1];
}
static void write_reg16(uint8_t blk, uint16_t a, uint16_t v) {
    uint8_t c[5] = { a >> 8, a, (uint8_t)(blk << 3 | WRITE), v >> 8, v };
    set_cs(1); write_data(c, 5); set_cs(0);
}
static void read_buf(uint8_t blk, uint16_t a, uint8_t *b, uint16_t n) {
    uint8_t c[3] = { a >> 8, a, (uint8_t)(blk << 3) };
    set_cs(1); write_data(c, 3); read_data(b, n); set_cs(0);
}
static void write_buf(uint8_t blk, uint16_t a, const uint8_t *b, uint16_t n) {
    uint8_t c[3] = { a >> 8, a, (uint8_t)(blk << 3 | WRITE) };
    set_cs(1); write_data(c, 3); write_data(b, n); set_cs(0);
}
static uint16_t read_reg16_safe(uint8_t blk, uint16_t a) {
    uint16_t v = 0, v1;
    do { v1 = read_reg16(blk, a); if (v1) v = read_reg16(blk, a); } while (v != v1);
    return v;
}
static int exec_cmd(uint8_t blk, uint8_t cmd) {        // CS held across both parts
    uint8_t c[4] = { 0x00, 0x01, (uint8_t)(blk << 3 | WRITE), cmd };
    set_cs(1); write_data(c, 4);
    c[2] = blk << 3;
    for (int i = 0; ; i++) {
        write_data(c, 3);
        if (read_byte() == 0) break;
        if (i > 1000) { set_cs(0); return -1; }
    }
    set_cs(0); return 0;
}

static int hw_init(const uint8_t mac[6]) {
    write_reg(0, 0x0000, 0x80);
    int i = 0; while (read_reg(0, 0x0000) & 0x80) if (i++ > 10) return -1;
    write_reg(0, 0x002E, 0x00); write_reg(0, 0x002E, 0xB8);
    if (read_reg(0, 0x0039) != 0x04) return -2;
    write_reg(0, 0x002C, 0);
    for (i = 0; i < 8; i++) { write_reg(1 + 4 * i, 0x1E, 0); write_reg(1 + 4 * i, 0x1F, 0); }
    write_reg(1, 0x1E, 16); write_reg(1, 0x1F, 16);
    write_buf(0, 0x0009, mac, 6);
    write_reg(1, 0x0000, 0x04 | 0x80);
    if (exec_cmd(1, 0x01) < 0) return -3;
    if (read_reg(1, 0x0003) != 0x42) return -4;
    return 0;
}
static int dc_tx(const uint8_t *pkt, int len) {
    if (!(read_reg(0, 0x2E) & 1)) return -1;
    uint16_t fsr = read_reg16_safe(1, 0x20);
    if (fsr < len) return -2;
    uint16_t wr = read_reg16(1, 0x24);
    write_buf(2, wr, pkt, len);
    write_reg16(1, 0x24, wr + len);
    return exec_cmd(1, 0x20);
}
static int dc_rx(uint8_t *out) {                       // returns length or 0
    uint16_t rsr = read_reg16_safe(1, 0x26);
    if (!rsr) return 0;
    uint16_t rd = read_reg16(1, 0x28);
    uint8_t h[2]; read_buf(3, rd, h, 2); rd += 2;
    uint16_t dl = (h[0] << 8 | h[1]) - 2;
    uint8_t mac[6]; read_buf(3, rd, mac, dl < 6 ? dl : 6);
    read_buf(3, rd, out, dl);
    rd += dl; write_reg16(1, 0x28, rd); exec_cmd(1, 0x40);
    return dl;
}

static void fill(uint8_t *p, int n, int seed) {
    for (int i = 0; i < n; i++) p[i] = (uint8_t)(seed * 31 + i * 7);
}

int main(void) {
    static const uint8_t mac[6] = { 0x00, 0xD0, 0xF1, 0x12, 0x34, 0x56 };
    w5500_init(&W);
    w5500_frame_start(&W);
    W.link_up = 0;

    int r = hw_init(mac);
    printf("hw_init -> %d\n", r); assert(r == 0);
    w5500_core0_service(&W); w5500_refresh(&W);
    assert(memcmp(&W.common[0x09], mac, 6) == 0);
    assert(W.sock_open && W.mac_filter);

    uint8_t pkt[1600], got[1600]; uint16_t gl;
    assert(dc_tx(pkt, 60) == -1);                     // link down -> refused like KOS
    W.link_up = 1; w5500_refresh(&W);

    // DC -> Pi: many frames, wraps the 16 KB ring several times
    long total = 0;
    for (int k = 0; k < 300; k++) {
        int len = 60 + (k * 97) % 1455;
        fill(pkt, len, k);
        r = dc_tx(pkt, len); assert(r == 0);
        assert(w5500_tx_pop(&W, got, &gl)); assert(gl == len);
        assert(memcmp(pkt, got, len) == 0);
        w5500_refresh(&W);
        total += len;
    }
    printf("DC->Pi: 300 frames, %ld bytes OK\n", total);

    // Pi -> DC: frames for us, broadcast, and someone else's (filtered)
    total = 0;
    for (int k = 0; k < 300; k++) {
        int len = 60 + (k * 131) % 1455;
        fill(pkt, len, k + 1000);
        if (k % 3 == 0) memcpy(pkt, mac, 6);
        else if (k % 3 == 1) memset(pkt, 0xFF, 6);
        else { memcpy(pkt, mac, 6); pkt[5] ^= 1; }
        assert(w5500_rx_push(&W, pkt, len));
        w5500_refresh(&W);
        int n = dc_rx(got);
        if (k % 3 == 2) { assert(n == 0); continue; }
        assert(n == len && memcmp(pkt, got, len) == 0);
        total += len;
    }
    printf("Pi->DC: 200 frames delivered, 100 filtered, %ld bytes OK\n", total);

    // Back-pressure: fill RX ring without the DC reading, then drain
    int queued = 0; memcpy(pkt, mac, 6);
    while (w5500_rx_push(&W, pkt, 1500)) { queued++; w5500_refresh(&W); }
    printf("RX ring holds %d full-size frames before back-pressure\n", queued);
    for (int k = 0; k < queued; k++) assert(dc_rx(got) == 1500);
    assert(dc_rx(got) == 0);

    // Soft reset mid-session resets pointers (core0 handshake)
    write_reg(0, 0x0000, 0x80);
    w5500_core0_service(&W); w5500_refresh(&W);
    assert(!W.sock_open && read_reg16(1, 0x26) == 0 && read_reg(0, 0x39) == 4);
    assert(hw_init(mac) == 0);
    printf("soft reset + re-init OK (resets=%u, cmds=%u)\n", W.st_resets, W.st_cmds);
    puts("ALL W5500 TESTS PASSED");
    return 0;
}
