// Dreamcast serial-port engine. Runs alone on core1 with no interrupts, so its
// response time to the Dreamcast is deterministic. The whole binary is linked
// copy_to_ram, so no flash cache misses on this path either.
//
// Mode logic
// ----------
//   SENSE  SPI slave state machine armed on PIO0 (MISO idles high, so a UART
//          receiver on the DC side just sees "idle"), low-pulse meter on PIO1
//          watching DC TXD. CTS asserted (pulled low) so a UART DC may talk.
//     -> UART  when >= SENSE_MIN_UART_PULSES low pulses arrive with NO SCLK
//              activity and their widths are integer multiples of one SCIF
//              bit time (640 ns * n).
//     SPI traffic is served directly in SENSE: there is no separate SPI mode,
//     the SPI engine is simply always armed while UART is not active.
//   UART   PIO1 UART RX/TX at the exact SCIF rate, RTS/CTS flow control.
//     -> SENSE when the DC starts driving its CTS pin as SCLK
//              (KOS scif_spi_init), or on a burst of framing errors / much
//              shorter pulses (baud change).
//
// SPI target (latched, survives SENSE<->UART changes)
//   SD     SCLK clocks while /CS is high: KOS sd_init() sends 80 of them.
//   W5500  write of MR with RST set (00 00 04 80): KOS w5500_soft_reset().
//
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/gpio.h"
#include "hardware/structs/iobank0.h"
#include "hardware/clocks.h"
#include "config.h"
#include "dcbus.h"
#include "sd_emu.h"
#include "dcbus.pio.h"

dcb_status_t dcb_status;
ring_t dcb_uart_rx, dcb_uart_tx;
w5500_t dcb_w5500;
sd_emu_t dcb_sd;
uint8_t dcb_sd_raw[DCB_SD_RAW_N];
volatile uint32_t dcb_sd_raw_n;
static uint32_t force_seen;
#define FORCED(f) (dcb_status.force == (f))
#define AUTO      (dcb_status.force == DCB_FORCE_AUTO)
static uint8_t uart_rx_buf[16384], uart_tx_buf[4096];

// PIO resources
#define PIO_SPI   pio0
#define SM_SPI    0
#define PIO_UART  pio1
#define SM_URX    0
#define SM_UTX    1
#define SM_PULSE  2
static uint off_spi, off_urx, off_utx, off_pulse;

// Raw edge latches in IO_BANK0 INTRx: 8 GPIOs per register, 4 bits per GPIO
// (level low, level high, edge low, edge high). Latched even with IRQs off.
#define EDGE_HIGH_REG(g) (&iobank0_hw->intr[(g) / 8])
#define EDGE_HIGH_BIT(g) (1u << (((g) % 8) * 4 + 3))

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------
static inline uint32_t now_ms(void) { return to_ms_since_boot(get_absolute_time()); }

// Cheap millisecond clock for the hot loop (no 64-bit division), wrap-safe.
static uint32_t __not_in_flash_func(fast_ms)(void) {
    static uint32_t ms, last_us;
    uint32_t d = time_us_32() - last_us;
    if (d >= 1000) {
        uint32_t k = d / 1000;          // hardware divider
        ms += k;
        last_us += k * 1000;
    }
    return ms;
}

// Returns true (and clears the latch) if a rising edge happened on gpio g.
static inline bool rose(uint g) {
    io_rw_32 *r = EDGE_HIGH_REG(g);
    uint32_t bit = EDGE_HIGH_BIT(g);
    if (!(*r & bit)) return false;
    *r = bit;                                  // write-1-to-clear
    return true;
}

// MISO filler used when the TX FIFO is empty (write phases, headers, underruns)
static uint8_t cur_filler = 0xFF;
static void __not_in_flash_func(set_filler)(uint8_t f) {
    if (f == cur_filler) return;
    cur_filler = f;
    PIO_SPI->instr_mem[off_spi + dc_spi_slave_offset_filler_msb] =
        pio_encode_set(pio_pins, f >> 7);
    PIO_SPI->instr_mem[off_spi + dc_spi_slave_offset_filler_byte] =
        f ? pio_encode_mov_not(pio_osr, pio_null) : pio_encode_mov(pio_osr, pio_null);
}

// CTS towards the Dreamcast (active low). Weak pulls on the SCLK/CTS pin always; optional
// stronger drive through a resistor on PIN_DC_CTS_DRIVE.
static bool cts_held;
static uint32_t ignore_sclk_until_us;
static void cts_set(bool allow) {
    if (allow == !cts_held) return;
    cts_held = !allow;
    if (allow) gpio_pull_down(PIN_DC_SCLK); else gpio_pull_up(PIN_DC_SCLK);
#if PIN_DC_CTS_DRIVE >= 0
    gpio_put(PIN_DC_CTS_DRIVE, !allow);
#endif
    if (!allow) dcb_status.cts_holds++;
    ignore_sclk_until_us = time_us_32() + 50;   // our own edge, not an SPI clock
}

static void set_mode(dcb_mode_t m) {
    if (dcb_status.mode == m) return;
    dcb_status.mode = m;
    dcb_status.mode_changes++;
}

// ---------------------------------------------------------------------------
// Engine (re)configuration
// ---------------------------------------------------------------------------
static void spi_restart(void) {
    pio_sm_set_enabled(PIO_SPI, SM_SPI, false);
    pio_sm_clear_fifos(PIO_SPI, SM_SPI);
    pio_sm_restart(PIO_SPI, SM_SPI);
    pio_sm_exec(PIO_SPI, SM_SPI, pio_encode_jmp(off_spi));
    PIO_SPI->irq = 1u;                                   // clear underrun flag
    gpio_set_function(PIN_DC_MISO, GPIO_FUNC_PIO0);
    w5500_frame_start(&dcb_w5500);
    pio_sm_set_enabled(PIO_SPI, SM_SPI, true);
}

static void enter_sense(void) {
    pio_sm_set_enabled(PIO_UART, SM_URX, false);
    pio_sm_set_enabled(PIO_UART, SM_UTX, false);
    set_filler(dcb_status.spi_target == DCB_SPI_W5500 ? 0x00 : 0xFF);
    cts_set(true);
    spi_restart();
    set_mode(DCB_MODE_SENSE);
}

static void enter_uart(uint32_t baud) {
    pio_sm_set_enabled(PIO_SPI, SM_SPI, false);
    // TX waits for the Dreamcast's RTS before each byte, unless flow control is off
    PIO_UART->instr_mem[off_utx + 1] = dcb_status.no_flow ? pio_encode_nop() : pio_encode_wait_pin(false, 0);
    dc_uart_rx_program_init(PIO_UART, SM_URX, off_urx, PIN_DC_MOSI, baud);
    dc_uart_tx_program_init(PIO_UART, SM_UTX, off_utx, PIN_DC_MISO, PIN_DC_CS, baud);
    gpio_set_function(PIN_DC_MISO, GPIO_FUNC_PIO1);
    PIO_UART->irq = 1u << 4;                              // clear framing flag
    pio_sm_set_enabled(PIO_UART, SM_URX, true);
    pio_sm_set_enabled(PIO_UART, SM_UTX, true);
    dcb_status.baud = baud;
    set_mode(DCB_MODE_UART);
}

void dcbus_init(void) {
    ring_init(&dcb_uart_rx, uart_rx_buf, sizeof uart_rx_buf);
    ring_init(&dcb_uart_tx, uart_tx_buf, sizeof uart_tx_buf);
    w5500_init(&dcb_w5500);
    memset((void *)&dcb_status, 0, sizeof dcb_status);
    sd_emu_init(&dcb_sd);

    // Pads. Inputs get pulls that define a safe level when the DC is off.
    gpio_init(PIN_DC_MOSI); gpio_pull_down(PIN_DC_MOSI);      // DC off -> reads low
    gpio_init(PIN_DC_CS);   gpio_pull_up(PIN_DC_CS);          // /CS idle high
    gpio_init(PIN_DC_SCLK); gpio_pull_down(PIN_DC_SCLK);      // CTS asserted
    gpio_init(PIN_DC_MISO);
#if PIN_DC_CTS_DRIVE >= 0
    gpio_init(PIN_DC_CTS_DRIVE);
    gpio_set_dir(PIN_DC_CTS_DRIVE, GPIO_OUT);
    gpio_put(PIN_DC_CTS_DRIVE, 0);
#endif
    // Schmitt triggers are on by default; keep slew slow on MISO (long cable)
    // MISO must settle within one SCLK half period (~60 ns at KOS fast speed)
    // through the SD adapters and wires: fast slew, 8 mA.
    gpio_set_slew_rate(PIN_DC_MISO, GPIO_SLEW_RATE_FAST);
    gpio_set_drive_strength(PIN_DC_MISO, GPIO_DRIVE_STRENGTH_8MA);

    off_spi   = pio_add_program(PIO_SPI, &dc_spi_slave_program);
    off_urx   = pio_add_program(PIO_UART, &dc_uart_rx_program);
    off_utx   = pio_add_program(PIO_UART, &dc_uart_tx_program);
    off_pulse = pio_add_program(PIO_UART, &dc_pulse_low_program);

    dc_spi_slave_program_init(PIO_SPI, SM_SPI, off_spi, PIN_DC_MOSI, PIN_DC_MISO, PIN_DC_SCLK, PIN_DC_CS);
    cur_filler = 0x00; set_filler(0xFF);
    dc_pulse_low_program_init(PIO_UART, SM_PULSE, off_pulse, PIN_DC_MOSI);
    pio_sm_set_enabled(PIO_UART, SM_PULSE, true);

    dcb_status.mode = DCB_MODE_UART;   // force a transition
    enter_sense();
}

// ---------------------------------------------------------------------------
// SPI byte handling (hot path)
// ---------------------------------------------------------------------------
static inline bool spi_rx_empty(void) {
    return PIO_SPI->fstat & (1u << (PIO_FSTAT_RXEMPTY_LSB + SM_SPI));
}
static inline uint8_t spi_rx_get(void) { return (uint8_t)PIO_SPI->rxf[SM_SPI]; }
static inline void spi_tx_put(uint8_t b) { PIO_SPI->txf[SM_SPI] = (uint32_t)b << 24; }
static inline bool spi_tx_full(void) {
    return PIO_SPI->fstat & (1u << (PIO_FSTAT_TXFULL_LSB + SM_SPI));
}

// Move queued virtual-SD output into the PIO TX FIFO and track busy/idle filler.
static void __not_in_flash_func(sd_top_up)(void) {
    uint8_t o;
    while (!spi_tx_full() && sd_emu_pull(&dcb_sd, &o)) spi_tx_put(o);
    set_filler(sd_emu_filler(&dcb_sd));
}

static uint32_t frame_bytes;      // bytes since /CS fell
static uint8_t  sniff[4];         // first bytes of the frame, for target detection

static void __not_in_flash_func(on_spi_byte)(uint8_t b) {
    uint8_t out[2];
    // KOS reads the write data-response with a single read right after the
    // CRC: answer it before anything else.
    if (dcb_sd.state == SD_S_W_CRC2 && dcb_status.spi_target == DCB_SPI_SD) {
        spi_tx_put((b == dcb_sd.expect_lo && dcb_sd.hi_ok) ? 0xE5 : 0xEB);
        dcb_sd.dr_sent = true;
    }
    dcb_status.spi_bytes++;
    if (frame_bytes < 4) sniff[frame_bytes] = b;
    frame_bytes++;

    switch (dcb_status.spi_target) {
    case DCB_SPI_SD:
        dcb_sd_raw[dcb_sd_raw_n++ % DCB_SD_RAW_N] = b;
        sd_emu_on_byte(&dcb_sd, b);
        sd_top_up();
        // A W5500 program started after an SD session: switch over and replay
        // its soft-reset frame into the emulator.
        if (AUTO && frame_bytes == 4 && sniff[0] == 0 && sniff[1] == 0 && sniff[2] == 0x04 && (sniff[3] & 0x80)) {
            dcb_status.spi_target = DCB_SPI_W5500;
            set_filler(0x00);
            w5500_frame_start(&dcb_w5500);
            for (int i = 0; i < 4; i++) w5500_on_byte(&dcb_w5500, sniff[i], out);
        }
        return;
    case DCB_SPI_NONE:
    case DCB_SPI_W5500:
    default: {
        int n = w5500_on_byte(&dcb_w5500, b, out);
        if (n) {
            spi_tx_put(out[0]);
            if (n > 1) { spi_tx_put(out[1]); PIO_SPI->irq = 1u; }  // read starts: arm underrun check
        }
        // Latch W5500 on the KOS soft reset: 00 00 04 80
        if (AUTO && frame_bytes == 4 && dcb_status.spi_target != DCB_SPI_W5500 &&
            sniff[0] == 0 && sniff[1] == 0 && sniff[2] == 0x04 && (sniff[3] & 0x80)) {
            dcb_status.spi_target = DCB_SPI_W5500;
            set_filler(0x00);
        }
        return;
    }
    }
}

static void __not_in_flash_func(on_frame_end)(void) {
    // Bytes still in the RX FIFO belong to the frame that just ended.
    while (!spi_rx_empty()) on_spi_byte(spi_rx_get());
    pio_sm_clear_fifos(PIO_SPI, SM_SPI);              // drop unused read-ahead
    if (dcb_status.spi_target != DCB_SPI_SD && dcb_w5500.state == 4 && (PIO_SPI->irq & 1u))
        dcb_status.spi_underruns++;                     // DC sampled filler on a read
    PIO_SPI->irq = 1u;
    if (frame_bytes) dcb_status.spi_frames++;
    frame_bytes = 0;
    w5500_frame_start(&dcb_w5500);
    sd_emu_frame_end(&dcb_sd);
}

// ---------------------------------------------------------------------------
// Baud meter
// ---------------------------------------------------------------------------
#define PULSE_SAMPLES 32
static uint32_t pulse_ns[PULSE_SAMPLES];
static int      pulse_n;

static inline uint32_t pulse_count_to_ns(uint32_t count) {
    // 2 cycles per loop + ~4 cycles of wait/mov overhead and 2-cycle input sync
    uint32_t cycles = 2 * count + 6;
    return (uint32_t)((uint64_t)cycles * 1000000u / (SYS_CLOCK_KHZ));
}

// Returns a baud rate once enough consistent pulses have been seen, else 0.
static uint32_t pulses_evaluate(void) {
    uint32_t min = UINT32_MAX;
    for (int i = 0; i < pulse_n; i++) if (pulse_ns[i] < min) min = pulse_ns[i];
    uint32_t bit_ns;
    uint32_t baud = dcbus_snap_baud(min, &bit_ns);
    if (!baud) return 0;
    // Most pulses must be whole multiples of the bit time (1..9 bits)
    int good = 0;
    for (int i = 0; i < pulse_n; i++) {
        uint32_t k = (pulse_ns[i] + bit_ns / 2) / bit_ns;
        if (k < 1 || k > 9) continue;
        int32_t e = (int32_t)pulse_ns[i] - (int32_t)(k * bit_ns);
        if (e < 0) e = -e;
        if ((uint32_t)e * 100 < bit_ns * 20) good++;
    }
    return good * 10 >= pulse_n * 8 ? baud : 0;
}

static void pulses_drain(bool keep) {
    while (!pio_sm_is_rx_fifo_empty(PIO_UART, SM_PULSE)) {
        uint32_t ns = pulse_count_to_ns(pio_sm_get(PIO_UART, SM_PULSE));
        if (!keep || ns < 300 || ns > 2000000) continue;   // glitches / idle-low gaps
        if (pulse_n < PULSE_SAMPLES) pulse_ns[pulse_n++] = ns;
    }
}

// ---------------------------------------------------------------------------
// Main loops
// ---------------------------------------------------------------------------
static void __not_in_flash_func(sense_loop)(void) {
    uint32_t win_start = time_us_32();
    uint32_t sclk_in_window = 0, sclk_cs_high = 0;
    uint32_t last_sclk_ms = fast_ms();
    bool spi_seen_in_window = false;
    pulse_n = 0;

    for (;;) {
        // 1. Hot path: SPI bytes. While a W5500 header is in flight spin here so
        //    the control byte is handled with minimum latency.
        while (!spi_rx_empty()) {
            on_spi_byte(spi_rx_get());
            uint32_t spin = 2000;
            while (((dcb_w5500.state && dcb_w5500.state < 3) || dcb_sd.state == SD_S_W_CRC2) &&
                   spi_rx_empty() && --spin) {}
        }
        // 2. /CS rose: frame boundary
        if (rose(PIN_DC_CS)) on_frame_end();

        // 3. SCLK activity bookkeeping (for SD detection, UART exclusion, idle filler)
        if (rose(PIN_DC_SCLK)) {
            sclk_in_window++;
            spi_seen_in_window = true;
            last_sclk_ms = fast_ms();
            dcb_status.last_activity_ms = last_sclk_ms;
            if (gpio_get(PIN_DC_CS)) {
                if (++sclk_cs_high >= 8 && dcb_status.spi_target != DCB_SPI_SD && AUTO) {
                    dcb_status.spi_target = DCB_SPI_SD;     // KOS sd_init() dummy clocks
                    dcb_status.spi_sd_sessions++;
                    set_filler(0xFF);
                }
            } else {
                sclk_cs_high = 0;
                if (dcb_status.spi_target == DCB_SPI_W5500) set_filler(0x00);
            }
        }

        // 4. Background work, only between bytes
        uint32_t ms = fast_ms();
        if (dcb_status.spi_target == DCB_SPI_W5500) {
            w5500_refresh(&dcb_w5500);
        } else if (dcb_status.spi_target == DCB_SPI_SD) {
            dcb_sd.now_ms = ms;
            sd_emu_poll(&dcb_sd);       // data from the Pi may have arrived
            sd_top_up();
        }

        // Idle bus: return MISO to "UART idle" so a DC that went back to SCIF
        // serial mode (KOS scif_spi_shutdown) never sees a break condition.
        // (The virtual SD card manages its own filler: it is 0xFF unless busy.)
        if (dcb_status.spi_target != DCB_SPI_SD && cur_filler != 0xFF && ms - last_sclk_ms > 20)
            set_filler(0xFF);

        // 5. Manual override changed?
        if (dcb_status.force_seq != force_seen) return;

        // 6. UART detection (not when forced to SD or W5500)
        uint32_t t = time_us_32();
        if (t - win_start >= SENSE_WINDOW_US) {
            bool uart_ok = AUTO || FORCED(DCB_FORCE_UART);
            pulses_drain(!spi_seen_in_window && uart_ok);
            if (spi_seen_in_window) pulse_n = 0;        // MOSI pulses were SPI data
            if (pulse_n >= SENSE_MIN_UART_PULSES) {
                uint32_t baud = pulses_evaluate();
                pulse_n = 0;
                if (baud) { enter_uart(baud); return; }
            }
            win_start = t;
            sclk_in_window = 0;
            spi_seen_in_window = false;
        }
    }
}

static void __not_in_flash_func(uart_loop)(void) {
    uint32_t win_start = time_us_32(), sclk_edges = 0, ferr_window = 0;
    uint32_t ferr_start = win_start;
    uint32_t bit_ns = 0;
    dcbus_snap_baud(1000000000u / dcb_status.baud, &bit_ns);
    pulse_n = 0;

    for (;;) {
        // DC -> Pi
        while (!pio_sm_is_rx_fifo_empty(PIO_UART, SM_URX)) {
            uint8_t b = (uint8_t)(pio_sm_get(PIO_UART, SM_URX) >> 24);
            if (ring_put(&dcb_uart_rx, b)) dcb_status.uart_rx_bytes++;
            else dcb_status.uart_overflows++;
        }
        // Flow control: hold the DC off while the Pi is not draining us
        uint32_t used = ring_used(&dcb_uart_rx);
        if (!cts_held && used > sizeof uart_rx_buf * 3 / 4) cts_set(false);
        else if (cts_held && used < sizeof uart_rx_buf / 4) cts_set(true);

        // Pi -> DC (the PIO program itself waits for the DC's RTS)
        uint8_t b;
        while (!pio_sm_is_tx_fifo_full(PIO_UART, SM_UTX) && ring_get(&dcb_uart_tx, &b)) {
            pio_sm_put(PIO_UART, SM_UTX, b);
            dcb_status.uart_tx_bytes++;
        }

        // Framing errors (IRQ 4 from the RX program)
        if (PIO_UART->irq & (1u << 4)) {
            PIO_UART->irq = 1u << 4;
            dcb_status.uart_framing_errors++;
            ferr_window++;
        }

        // The DC drives SCLK on its CTS pin => it switched to SPI
        if (rose(PIN_DC_SCLK) &&
            (int32_t)(time_us_32() - ignore_sclk_until_us) > 0)
            sclk_edges++;

        uint32_t t = time_us_32();
        if (dcb_status.force_seq != force_seen) return;
        bool fixed_baud = FORCED(DCB_FORCE_UART) && dcb_status.force_baud;
        if (t - win_start >= SENSE_WINDOW_US) {
            if (fixed_baud) {                        // forced: never leave UART
                pulses_drain(false);
                win_start = t; sclk_edges = 0; ferr_window = 0;
                continue;
            }
            if (sclk_edges >= SENSE_SCLK_EDGES_FOR_SPI && AUTO) { enter_sense(); return; }
            // Baud went up: pulses clearly shorter than our bit time
            pulses_drain(true);
            for (int i = 0; i < pulse_n; i++)
                if (pulse_ns[i] * 4 < bit_ns * 3) { enter_sense(); return; }
            pulse_n = 0;
            // Baud went down / garbage: framing error burst
            if (ferr_window > 8) { enter_sense(); return; }
            if (t - ferr_start >= 100000) { ferr_window = 0; ferr_start = t; }
            win_start = t;
            sclk_edges = 0;
        }
    }
}

// Apply a manual override requested over the control port.
static void apply_force(void) {
    force_seen = dcb_status.force_seq;
    switch (dcb_status.force) {
    case DCB_FORCE_SD:
        dcb_status.spi_target = DCB_SPI_SD;
        enter_sense();
        set_filler(0xFF);
        break;
    case DCB_FORCE_W5500:
        dcb_status.spi_target = DCB_SPI_W5500;
        enter_sense();
        set_filler(0x00);
        break;
    case DCB_FORCE_UART:
        if (dcb_status.force_baud) {
            if (dcb_status.mode == DCB_MODE_UART) enter_sense();   // re-init at the new rate
            enter_uart(dcb_status.force_baud);
        } else if (dcb_status.mode != DCB_MODE_UART) {
            enter_sense();                       // wait for traffic, measure the rate
        }
        break;
    default:
        break;                                   // auto: carry on from the current state
    }
}

void __not_in_flash_func(dcbus_core1_main)(void) {
    for (;;) {
        if (dcb_status.force_seq != force_seen) apply_force();
        if (dcb_status.mode == DCB_MODE_UART) uart_loop();
        else sense_loop();
    }
}
