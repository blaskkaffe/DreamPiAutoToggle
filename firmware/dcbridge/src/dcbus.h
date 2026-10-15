// Dreamcast bus engine (runs on core1).
#pragma once
#include <stdint.h>
#include "ring.h"
#include "w5500_emu.h"
#include "sd_emu.h"

typedef enum {
    DCB_MODE_SENSE = 0,   // SPI slave armed + baud meter running, MISO idles high
    DCB_MODE_UART,        // PIO UART active (PPP / console), flow control on CTS
} dcb_mode_t;

typedef enum {
    DCB_SPI_NONE = 0,     // no SPI master seen yet
    DCB_SPI_W5500,        // KOS w5500_adapter (latched on soft-reset write)
    DCB_SPI_SD,           // KOS sd.c / DreamShell (latched on clocks with /CS high)
} dcb_spi_target_t;

// Manual override (ctl command "mode ..."), for testing one function at a time
typedef enum {
    DCB_FORCE_AUTO = 0,   // detect everything (default)
    DCB_FORCE_SD,         // virtual SD card only
    DCB_FORCE_W5500,      // virtual W5500 only
    DCB_FORCE_UART,       // serial (PPP/console) only; force_baud 0 = auto-detect the rate
} dcb_force_t;

typedef struct {
    volatile dcb_mode_t       mode;
    volatile dcb_spi_target_t spi_target;
    volatile uint32_t baud;              // exact SH4 SCIF rate in UART mode
    volatile uint32_t mode_changes;
    volatile uint32_t uart_rx_bytes, uart_tx_bytes, uart_framing_errors, uart_overflows;
    volatile uint32_t spi_bytes, spi_frames, spi_underruns, spi_sd_sessions;
    volatile uint32_t cts_holds;         // times we told the DC to stop sending
    volatile uint32_t last_activity_ms;
    // override: core0 writes force/force_baud, then bumps force_seq
    volatile uint8_t  force;
    volatile bool     force_cable;  // UART baud follows the USB host's setting, like a coders cable
    volatile bool     no_flow;      // ignore the Dreamcast's RTS (programs that do not use RTS/CTS)
    volatile uint32_t force_baud;
    volatile uint32_t force_seq;
} dcb_status_t;

// Last MOSI bytes seen by the virtual SD card (diagnostics, "sdtrace")
#define DCB_SD_RAW_N 64u
extern uint8_t dcb_sd_raw[DCB_SD_RAW_N];
extern volatile uint32_t dcb_sd_raw_n;

extern dcb_status_t dcb_status;
extern ring_t   dcb_uart_rx;   // Dreamcast -> Pi   (core1 produces)
extern ring_t   dcb_uart_tx;   // Pi -> Dreamcast   (core0 produces)
extern w5500_t  dcb_w5500;
extern sd_emu_t dcb_sd;     // virtual SD card (core1 front end, core0 backend)

void dcbus_init(void);         // call on core0 before launching core1
void dcbus_core1_main(void);   // never returns

// Exposed for host testing of the baud snapper.
uint32_t dcbus_snap_baud(uint32_t min_low_ns, uint32_t *bit_ns_out);
uint32_t dcbus_kos_baud(uint32_t nominal);   // the real SCIF rate KOS uses for a nominal baud
