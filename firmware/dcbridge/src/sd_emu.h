// Virtual SD card for the Dreamcast (KallistiOS sd.c over SCIF-SPI, as used by
// openMenu's serial VMU feature and DreamShell). The card's contents live in a
// disk image on the Raspberry Pi; this module answers the SD protocol itself
// and only moves 512-byte sectors to and from the Pi.
//
// Threading model
//   core1: sd_emu_on_byte / sd_emu_pull / sd_emu_poll / sd_emu_frame_end
//          (the SPI hot path; never blocks)
//   core0: the sd_be_* backend functions, driven by sd_link.c (USB protocol)
//   Shared state: a sector cache (seqlock per entry, core0 writes), a ring of
//   finished write slots (core1 writes), a read-request ring (core1 -> core0)
//   and the session handshake counters.
//
// No Pico SDK dependencies: unit-tested on a PC by test/test_sd.c, which
// replays the KOS driver byte for byte.
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "w5500_emu.h"     // DCB_RAMFUNC

#define SD_SECTOR      512u
#define SD_CACHE_N     64u          // 32 KB of cached sectors, direct-mapped (lba % N); power of two
#define SD_WSLOTS      16u          // power of two; written sectors not yet acked by the Pi
#define SD_RQ_N        16u          // power of two
#define SD_PREFETCH    8u           // sectors fetched per cache miss
#define SD_LBA_NONE    0xFFFFFFFFu
#define SD_OUT_MAX     32u          // small prefix queue: R1/R3/R7, gaps, tokens, CSD/CID

typedef struct {
    volatile uint32_t seq;          // odd while core0 is rewriting the entry
    volatile uint32_t lba;
    uint16_t crc;                   // CRC16-CCITT of data, as the SD data block trailer
    uint8_t  data[SD_SECTOR];
} sd_cache_t;

typedef struct {
    uint32_t lba;
    uint16_t crc;
    uint8_t  data[SD_SECTOR];
} sd_wslot_t;

typedef struct {
    // ---------------- shared ----------------
    sd_cache_t cache[SD_CACHE_N];
    volatile uint32_t cache_gen;    // core0 bumps after every insert/invalidate
    sd_wslot_t wslot[SD_WSLOTS];
    volatile uint32_t w_head;       // core1: slots completed (CRC ok)
    volatile uint32_t w_tail;       // core0: slots acknowledged by the Pi
    volatile uint32_t rq[SD_RQ_N];
    volatile uint32_t rq_head;      // core1
    volatile uint32_t rq_tail;      // core0
    volatile uint32_t session_req;  // core1: bumped on CMD0
    volatile uint32_t session_idle_ms;  // bus idle time before that CMD0
    volatile uint32_t session_ready;    // core0: = session_req once the Pi said READY
    volatile uint32_t sectors;          // core0: image size from READY (0 = no image)
    volatile uint32_t now_ms;           // updated by the core1 glue loop

    // ---------------- statistics ----------------
    volatile uint32_t st_cmds, st_reads, st_writes, st_misses, st_crc_err, st_busy, st_sessions, st_torn;

    // ---------------- core1 private ----------------
    uint8_t  state;
    uint8_t  cmd[6];
    uint8_t  cmd_n;
    bool     app_cmd;
    bool     initialized;           // ACMD41 completed
    bool     multi;
    bool     first_block;
    bool     want_busy;
    uint32_t rd_lba, wr_lba;
    uint32_t seen_gen, req_ms;
    uint32_t last_activity_ms;
    uint32_t idle_before_ms;        // length of the last bus silence (> 50 ms)
    uint16_t wpos, wcrc;
    uint8_t  crc_hi;
    // MISO output: prefix bytes, then a sector streamed straight from the
    // cache or a write slot (no 512-byte copy on core1), then its CRC.
    uint8_t  out_rd, out_wr;
    uint8_t  out[SD_OUT_MAX];
    const uint8_t *src;
    uint16_t src_left;
    uint8_t  tail[2], tail_rd, tail_n;
    const volatile uint32_t *src_seq;   // seqlock of the cache entry being streamed
    uint32_t src_seq0;
} sd_emu_t;

// ---- setup (core0, before core1 starts) ----
void sd_emu_init(sd_emu_t *e);

// ---- core1 ----
void    sd_emu_on_byte(sd_emu_t *e, uint8_t mosi);  // every byte clocked with /CS low
bool    sd_emu_pull(sd_emu_t *e, uint8_t *b);       // next byte to queue on MISO
void    sd_emu_poll(sd_emu_t *e);                   // idle: deliver data that just arrived
void    sd_emu_frame_end(sd_emu_t *e);              // /CS went high
uint8_t sd_emu_filler(const sd_emu_t *e);           // 0xFF normally, 0x00 = busy

// ---- core0 backend ----
void     sd_be_cache_put(sd_emu_t *e, uint32_t lba, const uint8_t *data);
void     sd_be_invalidate(sd_emu_t *e);
bool     sd_be_cached(const sd_emu_t *e, uint32_t lba);
bool     sd_be_pop_request(sd_emu_t *e, uint32_t *lba);
uint32_t sd_be_writes_pending(const sd_emu_t *e);   // completed slots not yet acked
const sd_wslot_t *sd_be_write_slot(const sd_emu_t *e, uint32_t index);  // index = absolute counter
void     sd_be_write_acked(sd_emu_t *e);            // oldest slot is safe on the Pi
// invalidate: the Pi changed the image (applied queued edits) since our cache was filled
void     sd_be_session_ready(sd_emu_t *e, uint32_t session, uint32_t sectors, bool invalidate);

uint16_t sd_crc16(const uint8_t *p, uint32_t n);
