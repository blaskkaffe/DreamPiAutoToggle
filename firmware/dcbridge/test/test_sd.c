// Host test for the virtual SD card: the KallistiOS sd.c driver (ported
// faithfully below) talks byte by byte to sd_emu through a model of the PIO
// MISO FIFO, while sd_link talks to a fake Pi daemon with configurable delays.
// Build: cc -O2 -I../src test_sd.c ../src/sd_emu.c ../src/sd_link.c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include "sd_emu.h"
#include "sd_link.h"

// ---------------------------------------------------------------------------
// World model: 1 byte on the SPI bus = 1 us
// ---------------------------------------------------------------------------
static sd_emu_t E;
static uint64_t t_us;
static uint8_t fifo[4]; static int fifo_n;
static int cs_low;

#define IMG_SECTORS (64u * 2048u)          // 64 MiB image on the "Pi"
static uint8_t *img;
static int pi_has_image = 1;
static uint32_t pi_read_delay_us = 300, pi_ack_delay_us = 300, pi_ready_delay_us = 5000;
static uint32_t pi_sessions, pi_reads, pi_writes, pi_edit_next_session;

// ---- fake Pi: frames from the RP2040 land here --------------------------------
typedef struct { uint64_t due; uint8_t buf[6 + 520]; uint16_t n; } pending_t;
static pending_t pq[4096]; static int pq_n;
static uint8_t link_out[8192]; static uint32_t link_out_n;

static void pi_queue(uint64_t due, uint8_t type, const uint8_t *a, uint16_t alen, const uint8_t *b, uint16_t blen) {
    assert(pq_n < 4096);
    pending_t *p = &pq[pq_n++];
    p->due = due;
    uint16_t len = alen + blen;
    uint8_t h[6] = { 0xD5, 0xC3, type, 0, (uint8_t)len, (uint8_t)(len >> 8) };
    memcpy(p->buf, h, 6); memcpy(p->buf + 6, a, alen); if (blen) memcpy(p->buf + 6 + alen, b, blen);
    p->n = 6 + len;
}
static uint32_t rd32(const uint8_t *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }
static void w32(uint8_t *p, uint32_t v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }

static uint64_t pi_busy_until;   // the daemon is single-threaded: replies are in order
static void pi_handle(uint8_t type, const uint8_t *p, uint16_t len) {
    uint8_t a[12];
    uint64_t base = t_us > pi_busy_until ? t_us : pi_busy_until;
    switch (type) {
    case 0x01: break;   // HELLO
    case 0x02:          // SESSION
        pi_sessions++;
        w32(a, rd32(p)); w32(a + 4, pi_has_image ? IMG_SECTORS : 0);
        w32(a + 8, pi_edit_next_session);
        if (pi_edit_next_session) {           // apply a queued edit, like the daemon would
            memset(img + 5000 * 512, 0xAB, 512);
            pi_edit_next_session = 0;
        }
        pi_busy_until = base + pi_ready_delay_us;
        pi_queue(pi_busy_until, 0x81, a, 12, NULL, 0);
        break;
    case 0x03: {        // READ
        uint32_t lba = rd32(p); uint16_t cnt = p[4] | p[5] << 8;
        pi_reads++;
        for (uint16_t i = 0; i < cnt && lba + i < IMG_SECTORS; i++) {
            w32(a, lba + i);
            pi_busy_until = base + pi_read_delay_us + i * 520;   // ~1 MB/s USB
            pi_queue(pi_busy_until, 0x82, a, 4, img + (size_t)(lba + i) * 512, 512);
        }
        break;
    }
    case 0x04: {        // WRITE
        uint32_t lba = rd32(p);
        assert(len == 516 && lba < IMG_SECTORS);
        memcpy(img + (size_t)lba * 512, p + 4, 512);
        pi_writes++;
        w32(a, lba);
        pi_busy_until = base + pi_ack_delay_us;
        pi_queue(pi_busy_until, 0x83, a, 4, NULL, 0);
        break;
    }
    }
}
static void pi_parse(void) {
    uint32_t off = 0;
    while (link_out_n - off >= 6) {
        uint16_t len = link_out[off + 4] | link_out[off + 5] << 8;
        assert(link_out[off] == 0xD5 && link_out[off + 1] == 0xC3);
        if (link_out_n - off < 6u + len) break;
        pi_handle(link_out[off + 2], &link_out[off + 6], len);
        off += 6 + len;
    }
    memmove(link_out, link_out + off, link_out_n - off); link_out_n -= off;
}
static uint32_t io_write(const uint8_t *p, uint32_t n) {
    assert(link_out_n + n <= sizeof link_out); memcpy(link_out + link_out_n, p, n); link_out_n += n; return n;
}
static uint32_t io_room(void) { return 2048 - (link_out_n > 2048 ? 2048 : link_out_n); }
static void io_flush(void) { pi_parse(); }
static const sd_link_io_t IO = { io_write, io_room, io_flush };

static void deliver_due(void) {
    // in order of due time, only those due
    for (;;) {
        int best = -1;
        for (int i = 0; i < pq_n; i++) if (pq[i].due <= t_us && (best < 0 || pq[i].due < pq[best].due)) best = i;
        if (best < 0) return;
        sd_link_rx(pq[best].buf, pq[best].n);
        pq[best] = pq[--pq_n];
    }
}

// ---- core loops, run between bus bytes -------------------------------------
static void cores_tick(void) {
    E.now_ms = (uint32_t)(t_us / 1000);
    deliver_due();
    sd_link_service((uint32_t)(t_us / 1000), true);
    sd_emu_poll(&E);
    uint8_t b;
    while (fifo_n < 4 && sd_emu_pull(&E, &b)) fifo[fifo_n++] = b;
}

// ---- the SPI bus -------------------------------------------------------------
static uint8_t xfer(uint8_t mosi) {
    uint8_t miso = sd_emu_filler(&E);
    if (cs_low && fifo_n) { miso = fifo[0]; memmove(fifo, fifo + 1, --fifo_n); }
    t_us += 1;
    if (cs_low) {
        sd_emu_on_byte(&E, mosi);
        uint8_t b;
        while (fifo_n < 4 && sd_emu_pull(&E, &b)) fifo[fifo_n++] = b;
    }
    cores_tick();
    return miso;
}
static void set_cs(int enabled) {
    if (enabled) cs_low = 1;
    else if (cs_low) { cs_low = 0; fifo_n = 0; sd_emu_frame_end(&E); }
}
static void idle_us(uint32_t us) { while (us--) { t_us++; cores_tick(); } }

#include "kos_sd_port.h"

// ---------------------------------------------------------------------------
static uint32_t rnd(void) { static uint32_t s = 12345; s ^= s << 13; s ^= s >> 17; s ^= s << 5; return s; }

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    img = malloc((size_t)IMG_SECTORS * 512);
    for (size_t i = 0; i < (size_t)IMG_SECTORS * 512; i++) img[i] = (uint8_t)(i * 2654435761u >> 13);
    img[510] = 0x55; img[511] = 0xAA;
    sd_emu_init(&E);
    sd_link_init(&E, &IO);

    // 1. No image on the Pi: init must fail cleanly (openMenu "no SD")
    pi_has_image = 0;
    int r = sd_init();
    printf("init without image -> %d (expected failure)\n", r); assert(r != 0);
    pi_has_image = 1;

    // 2. Normal init after a cold boot; the Pi takes 5 ms to get ready
    idle_us(6000000);
    r = sd_init();
    printf("init -> %d, byte_mode=%d, sessions=%u, idle reported=%u ms, req=%u ready=%u sectors=%u\n", r, byte_mode, pi_sessions, E.session_idle_ms, E.session_req, E.session_ready, E.sectors);
    assert(r == 0 && !byte_mode && E.session_idle_ms >= 5000);
    uint64_t size = sd_get_size();
    printf("CSD size -> %llu bytes\n", (unsigned long long)size); assert(size == (uint64_t)IMG_SECTORS * 512);

    // 3. MBR + random reads, single and multi-block
    uint8_t *buf = malloc(64 * 512), *ref = malloc(64 * 512);
    assert(sd_read_blocks(0, 1, buf) == 0 && memcmp(buf, img, 512) == 0);
    for (int k = 0; k < 400; k++) {
        uint32_t n = 1 + rnd() % 16, lba = rnd() % (IMG_SECTORS - 16);
        assert(sd_read_blocks(lba, n, buf) == 0);
        assert(memcmp(buf, img + (size_t)lba * 512, n * 512) == 0);
    }
    printf("400 random reads OK (Pi read requests: %u, cache misses: %u)\n", pi_reads, E.st_misses);

    // 4. Writes, single and multi-block, then immediate read-back
    for (int k = 0; k < 300; k++) {
        uint32_t n = 1 + rnd() % 12, lba = rnd() % (IMG_SECTORS - 16);
        for (uint32_t i = 0; i < n * 512; i++) ref[i] = (uint8_t)rnd();
        assert(sd_write_blocks(lba, n, ref) == 0);
        assert(sd_read_blocks(lba, n, buf) == 0);
        assert(memcmp(buf, ref, n * 512) == 0);
    }
    idle_us(20000);
    assert(sd_be_writes_pending(&E) == 0);
    printf("300 random writes + read-back OK (Pi wrote %u sectors, crc errors %u)\n", pi_writes, E.st_crc_err);

    // 5. Slow Pi acks: write slots fill up, card signals busy, nothing is lost
    pi_ack_delay_us = 3000; uint32_t busy0 = E.st_busy;
    for (uint32_t i = 0; i < 48 * 512; i++) ref[i] = (uint8_t)rnd();
    assert(sd_write_blocks(1000, 48, ref) == 0);
    idle_us(200000);
    assert(memcmp(img + 1000 * 512, ref, 48 * 512) == 0);
    printf("48-sector write with slow acks OK (dropped tokens: %u)\n", E.st_busy - busy0);
    pi_ack_delay_us = 300;

    // 6. Pi too slow for one read (> KOS's ~50 ms): KOS re-inits and retries
    pi_read_delay_us = 70000; int re0 = reinits;
    r = sd_read_blocks(IMG_SECTORS - 100, 1, buf);
    pi_read_delay_us = 300;
    printf("very slow read -> %d after %d re-init(s)\n", r, reinits - re0);
    assert(r == 0 && memcmp(buf, img + (size_t)(IMG_SECTORS - 100) * 512, 512) == 0);
    printf("re-init reported bus idle of %u ms (Pi must NOT apply edits, < 5000)\n", E.session_idle_ms);
    assert(E.session_idle_ms < 5000);

    // 7. Edit applied by the Pi at a cold session start: cache must be dropped
    assert(sd_read_blocks(5000, 1, buf) == 0 && buf[0] != 0xAB);   // now cached
    pi_edit_next_session = 1;
    idle_us(6000000);
    assert(sd_init() == 0);
    assert(sd_read_blocks(5000, 1, buf) == 0 && buf[0] == 0xAB && buf[511] == 0xAB);
    puts("edit applied at cold session start is visible to the Dreamcast");

    free(buf); free(ref); free(img);
    puts("ALL SD TESTS PASSED");
    return 0;
}
