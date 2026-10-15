// End-to-end test: KOS sd.c (ported) -> sd_emu (core1 logic) -> sd_link (core0
// protocol) -> pty -> the real Python dcbridge-saves daemon -> image file.
// The SPI bus is paced at ~1 byte/us of real time, like a Dreamcast in fast mode.
// Started by test/e2e.py, which owns the daemon and the image.
//   test_e2e <pty-master-fd> <image-path>
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <time.h>
#include <unistd.h>
#include "sd_emu.h"
#include "sd_link.h"

static sd_emu_t E;
static int mfd;
static uint8_t fifo[4]; static int fifo_n;
static int cs_low;

static uint64_t now_us(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000u + ts.tv_nsec / 1000;
}
static uint64_t t0, bus_t;

// ---- link io: non-blocking pty with a local send buffer ----
static uint8_t txb[16384]; static uint32_t txn;
static uint32_t io_write(const uint8_t *p, uint32_t n) { memcpy(txb + txn, p, n); txn += n; return n; }
static uint32_t io_room(void) { return sizeof txb - txn; }
static void io_flush(void) {
    while (txn) {
        ssize_t w = write(mfd, txb, txn);
        if (w <= 0) return;
        memmove(txb, txb + w, txn - w); txn -= (uint32_t)w;
    }
}
static const sd_link_io_t IO = { io_write, io_room, io_flush };

static void cores_tick(void) {
    uint8_t buf[4096];
    ssize_t r;
    while ((r = read(mfd, buf, sizeof buf)) > 0) sd_link_rx(buf, (uint32_t)r);
    uint32_t ms = (uint32_t)((now_us() - t0) / 1000);
    E.now_ms = ms;
    sd_link_service(ms, true);
    sd_emu_poll(&E);
    uint8_t b;
    while (fifo_n < 4 && sd_emu_pull(&E, &b)) fifo[fifo_n++] = b;
}

static uint8_t xfer(uint8_t mosi) {
    while (now_us() < bus_t + 1) {}          // ~1 MB/s, like scif_spi_rw_byte
    bus_t = now_us();
    uint8_t miso = sd_emu_filler(&E);
    if (cs_low && fifo_n) { miso = fifo[0]; memmove(fifo, fifo + 1, --fifo_n); }
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
static void idle_us(uint32_t us) { uint64_t end = now_us() + us; while (now_us() < end) cores_tick(); }

#include "kos_sd_port.h"

static int imgfd;
static void img_read(uint32_t lba, uint32_t n, uint8_t *dst) {
    assert(pread(imgfd, dst, n * 512, (off_t)lba * 512) == (ssize_t)(n * 512));
}

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc < 3) return 2;
    mfd = atoi(argv[1]);
    fcntl(mfd, F_SETFL, fcntl(mfd, F_GETFL) | O_NONBLOCK);
    imgfd = open(argv[2], O_RDONLY);
    t0 = now_us();
    sd_emu_init(&E);
    sd_link_init(&E, &IO);

    idle_us(6000000);                          // a cold boot: bus silent > 5 s
    int r = sd_init();
    printf("sd_init over the real daemon -> %d (session idle %u ms)\n", r, E.session_idle_ms);
    if (r) return 1;
    uint64_t size = sd_get_size();
    off_t isz = lseek(imgfd, 0, SEEK_END);
    printf("card size %llu, image %lld\n", (unsigned long long)size, (long long)isz);
    if (size != (uint64_t)isz) return 1;

    // Read the first 2 MiB (MBR, FAT, root and the save folders) and compare
    // against the image file, which already contains the edit applied at init.
    static uint8_t a[16 * 512], b[16 * 512];
    uint64_t ts = now_us();
    for (uint32_t lba = 0; lba < 4096; lba += 16) {
        if (sd_read_blocks(lba, 16, a)) { printf("read error at %u\n", lba); return 1; }
        img_read(lba, 16, b);
        if (memcmp(a, b, sizeof a)) { printf("mismatch at %u\n", lba); return 1; }
    }
    double secs = (now_us() - ts) / 1e6;
    printf("read 2 MiB through the daemon OK: %.0f KB/s (%u misses)\n", 2048 / secs, E.st_misses);

    // Writes near the end of the image, read back, then check the file itself.
    uint32_t base = (uint32_t)(isz / 512) - 64;
    for (uint32_t i = 0; i < sizeof a; i++) a[i] = (uint8_t)(i * 7 + 3);
    ts = now_us();
    for (uint32_t k = 0; k < 4; k++)
        if (sd_write_blocks(base + k * 16, 16, a)) { puts("write error"); return 1; }
    printf("wrote 32 KiB: %.0f KB/s\n", 32 / ((now_us() - ts) / 1e6));
    if (sd_read_blocks(base + 16, 16, b) || memcmp(a, b, sizeof a)) { puts("read-back mismatch"); return 1; }
    idle_us(300000);
    img_read(base + 48, 16, b);
    if (memcmp(a, b, sizeof a)) { puts("daemon did not write the image"); return 1; }
    puts("writes reached the image file");
    puts("E2E OK");
    return 0;
}
