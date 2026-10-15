// Virtual WIZnet W5500 (MACRAW socket 0 only), as used by the KallistiOS
// w5500_adapter driver (kernel/arch/dreamcast/hardware/network/w5500_adapter.c).
//
// Threading model
//   core1 (Dreamcast SPI side) owns the register file and the frame decoder.
//   core0 (USB side) owns tx_rd / rx_wr and moves frames to/from CDC-ECM.
//   They communicate only through the volatile fields marked "shared".
//
// This file has no Pico SDK dependencies so it can be unit-tested on a PC.
#pragma once
#include <stdint.h>
#include <stdbool.h>

#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
#include "pico.h"
#define DCB_RAMFUNC(fn) __not_in_flash_func(fn)
#else
#define DCB_RAMFUNC(fn) fn
#endif

#define W5500_BUF_SIZE   16384u
#define W5500_BUF_MASK   (W5500_BUF_SIZE - 1)
#define W5500_SENDQ_LEN  32u           // power of two
#define W5500_MAX_FRAME  1514u
#define W5500_VERSION    0x04

typedef struct { uint16_t start, len; } w5500_send_t;

typedef struct {
    // ---------------- core1-owned register file ----------------
    uint8_t common[64];
    uint8_t sock[8][64];
    uint8_t txbuf[W5500_BUF_SIZE];     // socket 0 TX (16 KB, as KOS configures it)
    uint8_t rxbuf[W5500_BUF_SIZE];     // socket 0 RX
    uint8_t sink[1];                   // unsupported blocks read 0 / swallow writes

    // Block-select lookup (bsb 0..31) -> backing store; built once at init.
    uint8_t *base[32];
    uint16_t mask[32];

    // SPI frame decoder state (core1)
    uint8_t  state;
    uint8_t  bsb;
    uint16_t addr;

    uint8_t  phy_user;                 // PHYCFGR bits written by the driver
    uint16_t send_ptr;                 // where the next SEND starts (core1 private)
    uint32_t sendok_seen;

    // ---------------- shared: written by core1 ----------------
    volatile uint32_t sendq_head;
    w5500_send_t      sendq[W5500_SENDQ_LEN];
    volatile uint16_t rx_rd_committed; // Sn_RX_RD as of the last RECV command
    volatile bool     sock_open;       // socket 0 open in MACRAW
    volatile bool     mac_filter;      // Sn_MR.MFEN
    volatile uint32_t reset_req;       // bump to ask core0 to zero its pointers

    // ---------------- shared: written by core0 ----------------
    volatile uint32_t sendq_tail;
    volatile uint16_t tx_rd;           // advanced after a frame was taken
    volatile uint16_t rx_wr;           // advanced after a frame was appended
    volatile uint32_t reset_ack;
    volatile bool     link_up;         // USB network interface is up on the Pi
    volatile uint32_t sendok_count;

    // ---------------- statistics ----------------
    volatile uint32_t st_frames_tx, st_frames_rx, st_drop_rx_full, st_drop_rx_filter,
                      st_drop_tx, st_cmds, st_resets;
} w5500_t;

// ---- core1 API ----
void w5500_init(w5500_t *w);                 // power-on state
static inline void w5500_frame_start(w5500_t *w) { w->state = 0; }  // call on /CS rise
// Feed one MOSI byte. Returns how many bytes (0..2) were written to out[] that
// must be queued for MISO, in order. Must be fast: see dcbus.c.
int  w5500_on_byte(w5500_t *w, uint8_t in, uint8_t out[2]);
void w5500_refresh(w5500_t *w);              // recompute FSR/RSR/link; call when idle

// ---- core0 API ----
// Copies the next frame the Dreamcast SENT into dst (>= W5500_MAX_FRAME bytes).
bool w5500_tx_pop(w5500_t *w, uint8_t *dst, uint16_t *len);
// Offers a frame from the Pi. Returns false only when the RX buffer is full
// (keep the frame and retry); filtered/closed-socket frames return true.
bool w5500_rx_push(w5500_t *w, const uint8_t *frame, uint16_t len);
void w5500_core0_service(w5500_t *w);        // reset handshake; call every loop
