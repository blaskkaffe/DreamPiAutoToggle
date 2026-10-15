// USB side of the virtual SD card (core0): a small framed protocol over the
// "dcbridge disk" CDC port, spoken by the Pi's dcbridge-saves daemon.
//
// Frame: D5 C3 <type> 00 <len lo> <len hi> <payload...>  (little-endian fields)
//   RP2040 -> Pi                         Pi -> RP2040
//   01 HELLO   proto u16, cache u16      81 READY  session u32, sectors u32, flags u32
//                                           (flags bit 0: image edited, drop cache)
//   02 SESSION session u32, idle_ms u32  82 DATA   lba u32, data[512]
//   03 READ    lba u32, count u16        83 WACK   lba u32
//   04 WRITE   lba u32, data[512]
// USB bulk transfers are CRC-checked and reliable, so frames carry no checksum.
// The sync bytes only matter for re-synchronising after a daemon restart.
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "sd_emu.h"

#define SDL_PROTO_VERSION 1
#define SDL_HDR       6
#define SDL_HELLO     0x01
#define SDL_SESSION   0x02
#define SDL_READ      0x03
#define SDL_WRITE     0x04
#define SDL_READY     0x81
#define SDL_DATA      0x82
#define SDL_WACK      0x83

typedef struct {
    uint32_t (*write)(const uint8_t *p, uint32_t n);   // returns bytes accepted
    uint32_t (*room)(void);                            // bytes that can be written now
    void     (*flush)(void);
} sd_link_io_t;

typedef struct {
    volatile uint32_t frames_rx, frames_tx, resyncs, reads_sent, writes_sent;
    volatile bool     daemon_seen;     // got at least one frame since connect
} sd_link_stats_t;

extern sd_link_stats_t sd_link_stats;

void sd_link_init(sd_emu_t *e, const sd_link_io_t *io);
void sd_link_rx(const uint8_t *p, uint32_t n);
void sd_link_service(uint32_t now_ms, bool connected);
