// dcbridge - Dreamcast serial-port bridge for RP2040
// Board / pin / tuning configuration.
#pragma once

// ---------------------------------------------------------------------------
// Bus A: Dreamcast serial port (all handled by PIO, never by UART0/SPI0 HW).
//
// Signal roles per KOS scif-spi.c (SCSPTR2 bit-bang):
//   DC TXD  (SPB2DT out)  = UART TX  / SPI MOSI   -> always DC output
//   DC RXD  (SPB2DT in)   = UART RX  / SPI MISO   -> always DC input
//   DC RTS  (RTSDT)       = UART RTS / SPI /CS    -> always DC output
//   DC CTS  (CTSDT)       = UART CTS / SPI SCLK   -> DC INPUT in UART mode,
//                                                    DC OUTPUT in SPI mode
// The CTS/SCLK line is the only one whose direction flips, so the RP2040
// never drives it hard: in UART mode we signal flow control with the weak
// internal pulls only (see dcbus.c), so a DC that switches to SPI simply
// overpowers us and we see SCLK edges.
// ---------------------------------------------------------------------------
// Physical chain: Dreamcast serial port -> serial-to-SD adapter -> SD-to-microSD
// adapter -> microSD pads soldered to the RP2040. The RP2040 sits where the card
// would be, so each microSD pad carries a Dreamcast serial line:
//   microSD pin 2 DAT3/CS <- DC RTS    pin 3 CMD  <- DC TXD
//   microSD pin 5 CLK     <> DC CTS    pin 7 DAT0 -> DC RXD
//   pin 4 VDD: left unconnected on purpose (the adapter powers its own side,
//   the RP2040 is powered by USB). pin 6 VSS: common ground.
// The pins need not be contiguous: the PIO program's waits are patched to
// absolute GPIO numbers at load time.
#define PIN_DC_SCLK   2   // microSD 5 CLK      = DC CTS / SPI SCLK
#define PIN_DC_MOSI   3   // microSD 3 CMD      = DC TXD / SPI MOSI
#define PIN_DC_MISO   4   // microSD 7 DAT0     = DC RXD / SPI MISO
#define PIN_DC_CS     5   // microSD 2 DAT3/CS  = DC RTS / SPI /CS
// Optional: GP6 -> 1 kOhm -> the CLK line (GP2), for UART-mode flow control
// strong enough to beat any pull-up in the adapter. -1 if not fitted.
#define PIN_DC_CTS_DRIVE 6

#define PIN_LED       25  // Pico on-board LED

// ---------------------------------------------------------------------------
// Clocks. The W5500 read path has a hard deadline (first data bit must be on
// MISO before the DC's next SCLK rising edge, ~150-250 ns after the header).
// 250 MHz gives core1 roughly 40-60 cycles for it. Hot code runs from RAM.
// ---------------------------------------------------------------------------
#define SYS_CLOCK_KHZ 250000

// Dreamcast SH4 peripheral clock and SCIF baud formula (KOS scif.c):
//   SCBRR2 = 50000000 / (32 * baud) - 1   (CKS = 0)
#define DC_PCLK_HZ    50000000u

// Sense / mode-switch tuning
#define SENSE_MIN_UART_PULSES    24     // low pulses needed before trusting a baud estimate
#define SENSE_SCLK_EDGES_FOR_SPI 8      // SCLK rising edges inside one window => SPI master present
#define SENSE_WINDOW_US          200

// USB identity: pid.codes test VID/PID, fine for a private device. The Pi's
// udev rules also match the manufacturer string "dcbridge", so if you get your own
// PID later only these two lines and the rules file change.
#define USB_VID       0x1209
#define USB_PID       0x0001
#define USB_BCD       0x0100

// --- Pin sanity checks --------------------------------------------------------
#if PIN_DC_CTS_DRIVE == PIN_DC_SCLK || PIN_DC_CTS_DRIVE == PIN_DC_MOSI || \
    PIN_DC_CTS_DRIVE == PIN_DC_MISO || PIN_DC_CTS_DRIVE == PIN_DC_CS
#error "PIN_DC_CTS_DRIVE overlaps a Dreamcast line"
#endif
