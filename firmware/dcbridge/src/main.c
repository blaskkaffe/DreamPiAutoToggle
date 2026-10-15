// dcbridge - core0: clocks, USB composite device, data pumps, control channel.
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "pico/bootrom.h"
#include "hardware/vreg.h"
#include "hardware/clocks.h"
#include "hardware/watchdog.h"
#include "tusb.h"
#include "config.h"
#include "usb_descriptors.h"
#include "dcbus.h"
#include "sd_link.h"
#include "settings.h"

// ---------------------------------------------------------------------------
// CDC 0: Dreamcast UART <-> /dev/dcbridge-uart (pppd)
// ---------------------------------------------------------------------------
static void uart_pump(void) {
    const bool host_open = tud_cdc_n_connected(CDC_UART);   // DTR set (pppd is running)

    // DC -> Pi. With nobody listening, discard instead of stalling the DC.
    const uint8_t *p;
    uint32_t n;
    while ((n = ring_peek_span(&dcb_uart_rx, &p)) != 0) {
        if (host_open) {
            uint32_t room = tud_cdc_n_write_available(CDC_UART);
            if (!room) break;
            if (n > room) n = room;
            n = tud_cdc_n_write(CDC_UART, p, n);
        }
        ring_consume(&dcb_uart_rx, n);
    }
    if (host_open) tud_cdc_n_write_flush(CDC_UART);

    // Pi -> DC. Only while the DC is actually in UART mode: DreamPi's modem
    // probe (wvdialconf) opens every ttyACM and sends AT commands, and those
    // must not reach a Dreamcast that is in SPI mode or not listening.
    while (tud_cdc_n_available(CDC_UART)) {
        uint8_t buf[64];
        uint32_t room = ring_free(&dcb_uart_tx);
        if (dcb_status.mode == DCB_MODE_UART && room == 0) break;   // back-pressure USB
        uint32_t want = room < sizeof buf ? room : sizeof buf;
        if (dcb_status.mode != DCB_MODE_UART) want = sizeof buf;
        uint32_t got = tud_cdc_n_read(CDC_UART, buf, want);
        if (dcb_status.mode != DCB_MODE_UART) continue;             // drop
        for (uint32_t i = 0; i < got; i++) ring_put(&dcb_uart_tx, buf[i]);
    }
}

// ---------------------------------------------------------------------------
// CDC-ECM: virtual W5500 <-> usb0 on the Pi
// ---------------------------------------------------------------------------
static volatile bool net_up;
static const uint8_t *rx_pending;
static uint16_t rx_pending_len;

void tud_network_init_cb(void) {
    net_up = true;
    rx_pending = NULL;
}

bool tud_network_recv_cb(const uint8_t *src, uint16_t size) {
    if (w5500_rx_push(&dcb_w5500, src, size)) {
        tud_network_recv_renew();
        return true;
    }
    rx_pending = src;              // RX ring full: hold the USB buffer (NAKs the host)
    rx_pending_len = size;
    return true;
}

uint16_t tud_network_xmit_cb(uint8_t *dst, void *ref, uint16_t arg) {
    (void)ref; (void)arg;
    uint16_t len = 0;
    if (!w5500_tx_pop(&dcb_w5500, dst, &len)) return 0;
    return len;
}

static void net_pump(void) {
    w5500_core0_service(&dcb_w5500);
    dcb_w5500.link_up = net_up && tud_mounted();

    if (rx_pending && w5500_rx_push(&dcb_w5500, rx_pending, rx_pending_len)) {
        rx_pending = NULL;
        tud_network_recv_renew();
    }

    if (dcb_w5500.sendq_head != dcb_w5500.sendq_tail) {
        if (!dcb_w5500.link_up) {
            static uint8_t sink[W5500_MAX_FRAME];
            uint16_t len;
            while (w5500_tx_pop(&dcb_w5500, sink, &len)) {}       // keep TX_FSR free
        } else if (tud_network_can_xmit(W5500_MAX_FRAME)) {
            tud_network_xmit(NULL, 0);                             // -> tud_network_xmit_cb
        }
    }
}

void tud_umount_cb(void) { net_up = false; }
void tud_suspend_cb(bool remote_wakeup_en) { (void)remote_wakeup_en; net_up = false; }

// ---------------------------------------------------------------------------
// CDC 2: virtual SD card sectors <-> /dev/dcbridge-disk (dcbridge-saves daemon)
// ---------------------------------------------------------------------------
static uint32_t disk_write(const uint8_t *p, uint32_t n) { return tud_cdc_n_write(CDC_DISK, p, n); }
static uint32_t disk_room(void) { return tud_cdc_n_write_available(CDC_DISK); }
static void disk_flush(void) { tud_cdc_n_write_flush(CDC_DISK); }
static const sd_link_io_t disk_io = { disk_write, disk_room, disk_flush };

static void disk_pump(void) {
    uint8_t buf[256];
    while (tud_cdc_n_available(CDC_DISK)) {
        uint32_t n = tud_cdc_n_read(CDC_DISK, buf, sizeof buf);
        sd_link_rx(buf, n);
    }
    sd_link_service(to_ms_since_boot(get_absolute_time()), tud_cdc_n_connected(CDC_DISK));
}

// ---------------------------------------------------------------------------
// CDC 1: control / status (one JSON object per line) -> /dev/dcbridge-ctl
// Commands: "status", "reboot", "bootsel" (reflash from the Pi with picotool or
// by copying a .uf2 to the RPI-RP2 drive that appears).
// ---------------------------------------------------------------------------
static const char *mode_name(void) {
    return dcb_status.mode == DCB_MODE_UART ? "uart" : "sense";
}
static const char *target_name(void) {
    switch (dcb_status.spi_target) {
    case DCB_SPI_W5500: return "w5500";
    case DCB_SPI_SD:    return "sd";
    default:            return "none";
    }
}

static const char *force_name(void) {
    switch (dcb_status.force) {
    case DCB_FORCE_SD:    return "sd";
    case DCB_FORCE_W5500: return "w5500";
    case DCB_FORCE_UART:  return dcb_status.force_cable ? "cable" : "uart";
    default:              return "auto";
    }
}

static uint32_t host_baud;          // last rate the USB host set on /dev/dcbridge-uart

static void apply_force(uint8_t f, bool cable, uint32_t baud) {
    if (cable && host_baud) baud = dcbus_kos_baud(host_baud);
    dcb_status.force = f;
    dcb_status.force_cable = (f == DCB_FORCE_UART) && cable;
    dcb_status.force_baud = (f == DCB_FORCE_UART) ? baud : 0;
    __dmb();
    dcb_status.force_seq++;
}

// "mode auto|sd|w5500|cable|uart [baud] [save]"
//   cable : plain USB-serial coders cable; the UART runs at the rate the host
//           program opens /dev/dcbridge-uart with (mapped to the real SCIF rate)
//   uart  : serial only; fixed [baud], or measured from the Dreamcast's traffic
//   noflow: do not wait for the Dreamcast's RTS (dcload-serial and other
//           programs that run the SCIF without RTS/CTS)
//   save  : also store it in flash as the power-on mode
static bool set_force(const char *arg) {
    uint8_t f;
    bool cable = false, save = false, noflow = false;
    uint32_t baud = 0;
    char name[12] = {0};
    int i = 0;
    while (*arg == ' ') arg++;
    while (*arg && *arg != ' ' && i < (int)sizeof name - 1) name[i++] = *arg++;
    while (*arg) {
        while (*arg == ' ') arg++;
        if (*arg >= '0' && *arg <= '9') {
            baud = 0;
            while (*arg >= '0' && *arg <= '9') baud = baud * 10 + (uint32_t)(*arg++ - '0');
        } else if (!strncmp(arg, "save", 4)) {
            save = true; arg += 4;
        } else if (!strncmp(arg, "noflow", 6)) {
            noflow = true; arg += 6;
        } else if (*arg) {
            return false;
        }
    }
    if (!strcmp(name, "auto")) f = DCB_FORCE_AUTO;
    else if (!strcmp(name, "sd")) f = DCB_FORCE_SD;
    else if (!strcmp(name, "w5500")) f = DCB_FORCE_W5500;
    else if (!strcmp(name, "cable")) { f = DCB_FORCE_UART; cable = true; }
    else if (!strcmp(name, "uart") || !strcmp(name, "ppp") || !strcmp(name, "serial")) f = DCB_FORCE_UART;
    else return false;
    if (baud) {
        if (baud < 300 || baud > 1562500) return false;
        baud = dcbus_kos_baud(baud);          // "115200" means what KOS means by it
    }
    dcb_status.no_flow = noflow;
    apply_force(f, cable, baud);
    if (save) {
        dcb_settings_t st;
        memset(&st, 0, sizeof st);            // padding included in the checksum
        st.force = f; st.cable = cable; st.noflow = noflow; st.baud = cable ? 0 : baud;
        settings_save(&st);
    }
    return true;
}

// Coders-cable behaviour: follow the baud rate the host program asks for.
void tud_cdc_line_coding_cb(uint8_t itf, cdc_line_coding_t const *coding) {
    if (itf != CDC_UART) return;
    host_baud = coding->bit_rate;
    if (dcb_status.force == DCB_FORCE_UART && dcb_status.force_cable && host_baud) {
        uint32_t b = dcbus_kos_baud(host_baud);
        if (b != dcb_status.force_baud) apply_force(DCB_FORCE_UART, true, b);
    }
}

static void ctrl_line(const char *text) {
    uint32_t n = (uint32_t)strlen(text);
    if (n <= tud_cdc_n_write_available(CDC_CTRL)) {
        tud_cdc_n_write(CDC_CTRL, text, n);
        tud_cdc_n_write_flush(CDC_CTRL);
    }
}

// --- "sdtrace": dump the virtual SD card's recent history, a chunk per call ---
static const char *const EV_NAME[] = { "?", "cmd", "ready", "miss", "served", "write_ok",
                                       "write_crc_err", "abort", "busy" };
static int trace_step = -1;          // -1 idle, 0.. chunks
static uint32_t trace_end;

static void trace_pump(void) {
    if (trace_step < 0) return;
    if (tud_cdc_n_write_available(CDC_CTRL) < 900) return;
    static char line[900];             // static: core0 stack is only 2 KB
    int n = 0;
    if (trace_step == 0) {
        trace_end = dcb_sd.trace_n;
        n = snprintf(line, sizeof line,
            "{\"sdstate\":{\"forced\":\"%s\",\"target\":\"%s\",\"state\":%u,\"initialized\":%s,"
            "\"session_req\":%lu,\"session_ready\":%lu,\"sectors\":%lu,\"daemon\":%s,"
            "\"cmds\":%lu,\"reads\":%lu,\"writes\":%lu,\"misses\":%lu,\"crc_err\":%lu,"
            "\"torn\":%lu,\"w_pending\":%lu,\"events\":%lu,\"raw_bytes\":%lu}}\r\n",
            force_name(), target_name(), dcb_sd.state, dcb_sd.initialized ? "true" : "false",
            (unsigned long)dcb_sd.session_req, (unsigned long)dcb_sd.session_ready,
            (unsigned long)dcb_sd.sectors, sd_link_stats.daemon_seen ? "true" : "false",
            (unsigned long)dcb_sd.st_cmds, (unsigned long)dcb_sd.st_reads,
            (unsigned long)dcb_sd.st_writes, (unsigned long)dcb_sd.st_misses,
            (unsigned long)dcb_sd.st_crc_err, (unsigned long)dcb_sd.st_torn,
            (unsigned long)sd_be_writes_pending(&dcb_sd), (unsigned long)trace_end,
            (unsigned long)dcb_sd_raw_n);
    } else if (trace_step <= 4) {
        // events, oldest first, 16 per line
        uint32_t total = trace_end < SD_TRACE_N ? trace_end : SD_TRACE_N;
        uint32_t first = trace_end - total, k0 = (uint32_t)(trace_step - 1) * 16;
        n = snprintf(line, sizeof line, "{\"sdtrace\":[");
        for (uint32_t k = k0; k < k0 + 16 && k < total && n < (int)sizeof line - 64; k++) {
            const sd_trace_t *t = &dcb_sd.trace[(first + k) % SD_TRACE_N];
            uint8_t ty = t->type < 9 ? t->type : 0;
            n += snprintf(line + n, sizeof line - n, "%s[%lu,\"%s\",%u,%u,%lu]", k > k0 ? "," : "",
                          (unsigned long)t->t_ms, EV_NAME[ty], t->a, t->b, (unsigned long)t->arg);
        }
        n += snprintf(line + n, sizeof line - n, "]}\r\n");
        if (k0 >= total) n = 0;               // nothing in this chunk
    } else {
        // last MOSI bytes, oldest first
        uint32_t end = dcb_sd_raw_n, cnt = end < DCB_SD_RAW_N ? end : DCB_SD_RAW_N;
        n = snprintf(line, sizeof line, "{\"sdraw\":\"");
        for (uint32_t k = end - cnt; k != end; k++)
            n += snprintf(line + n, sizeof line - n, "%02x", dcb_sd_raw[k % DCB_SD_RAW_N]);
        n += snprintf(line + n, sizeof line - n, "\"}\r\n");
        trace_step = -2;
    }
    if (n > 0) ctrl_line(line);
    trace_step++;
}

static void ctrl_status(void) {
    if (!tud_cdc_n_connected(CDC_CTRL)) return;
    static char line[1024];            // static: core0 stack is only 2 KB
    int n = snprintf(line, sizeof line,
        "{\"fw\":\"dcbridge-0.3\",\"uptime_ms\":%lu,\"forced\":\"%s\",\"forced_baud\":%lu,"
        "\"host_baud\":%lu,\"flow\":%s,\"cts_line\":%d,"
        "\"mode\":\"%s\",\"spi\":\"%s\","
        "\"baud\":%lu,\"mode_changes\":%lu,"
        "\"uart\":{\"rx\":%lu,\"tx\":%lu,\"ferr\":%lu,\"ovf\":%lu,\"cts_holds\":%lu},"
        "\"spi_bus\":{\"bytes\":%lu,\"frames\":%lu,\"underruns\":%lu,\"sd_sessions\":%lu},"
        "\"w5500\":{\"open\":%s,\"link\":%s,\"tx\":%lu,\"rx\":%lu,\"drop_tx\":%lu,"
        "\"rx_full\":%lu,\"resets\":%lu},"
        "\"sd\":{\"daemon\":%s,\"ready\":%s,\"sessions\":%lu,\"reads\":%lu,\"writes\":%lu,"
        "\"misses\":%lu,\"crc_err\":%lu,\"busy_drops\":%lu,\"pending_writes\":%lu}}\r\n",
        (unsigned long)to_ms_since_boot(get_absolute_time()), force_name(),
        (unsigned long)dcb_status.force_baud, (unsigned long)host_baud,
        dcb_status.no_flow ? "false" : "true",
        gpio_get(PIN_DC_SCLK) ? 1 : 0, mode_name(), target_name(),
        (unsigned long)(dcb_status.mode == DCB_MODE_UART ? dcb_status.baud : 0),
        (unsigned long)dcb_status.mode_changes,
        (unsigned long)dcb_status.uart_rx_bytes, (unsigned long)dcb_status.uart_tx_bytes,
        (unsigned long)dcb_status.uart_framing_errors, (unsigned long)dcb_status.uart_overflows,
        (unsigned long)dcb_status.cts_holds,
        (unsigned long)dcb_status.spi_bytes, (unsigned long)dcb_status.spi_frames,
        (unsigned long)dcb_status.spi_underruns, (unsigned long)dcb_status.spi_sd_sessions,
        dcb_w5500.sock_open ? "true" : "false", dcb_w5500.link_up ? "true" : "false",
        (unsigned long)dcb_w5500.st_frames_tx, (unsigned long)dcb_w5500.st_frames_rx,
        (unsigned long)dcb_w5500.st_drop_tx, (unsigned long)dcb_w5500.st_drop_rx_full,
        (unsigned long)dcb_w5500.st_resets,
        sd_link_stats.daemon_seen ? "true" : "false",
        (dcb_sd.session_ready == dcb_sd.session_req && dcb_sd.sectors) ? "true" : "false",
        (unsigned long)dcb_sd.st_sessions, (unsigned long)dcb_sd.st_reads,
        (unsigned long)dcb_sd.st_writes, (unsigned long)dcb_sd.st_misses,
        (unsigned long)dcb_sd.st_crc_err, (unsigned long)dcb_sd.st_busy,
        (unsigned long)sd_be_writes_pending(&dcb_sd));
    if (n >= (int)sizeof line) n = (int)sizeof line - 1;      // never past the buffer
    if (n > 0 && (uint32_t)n <= tud_cdc_n_write_available(CDC_CTRL)) {
        tud_cdc_n_write(CDC_CTRL, line, (uint32_t)n);
        tud_cdc_n_write_flush(CDC_CTRL);
    }
}

static void ctrl_pump(void) {
    static char cmd[32];
    static uint8_t cmd_len;
    static uint32_t last_ms, last_changes, last_target;
    uint32_t now = to_ms_since_boot(get_absolute_time());

    while (tud_cdc_n_available(CDC_CTRL)) {
        char c = (char)tud_cdc_n_read_char(CDC_CTRL);
        if (c == '\r' || c == '\n') {
            cmd[cmd_len] = 0;
            if (!strcmp(cmd, "status")) ctrl_status();
            else if (!strcmp(cmd, "reboot")) watchdog_reboot(0, 0, 10);
            else if (!strcmp(cmd, "bootsel")) reset_usb_boot(1u << PIN_LED, 0);
            else if (!strcmp(cmd, "sdtrace")) trace_step = 0;
            else if (!strncmp(cmd, "mode ", 5)) {
                if (!set_force(cmd + 5))
                    ctrl_line("{\"error\":\"usage: mode auto|sd|w5500|cable|uart [baud] [noflow] [save]\"}\r\n");
                else ctrl_status();
            }
            cmd_len = 0;
        } else if (cmd_len < sizeof cmd - 1) {
            cmd[cmd_len++] = c;
        }
    }
    trace_pump();
    // Periodic status, and immediately on a mode/target change
    if (now - last_ms >= 1000 || dcb_status.mode_changes != last_changes ||
        dcb_status.spi_target != last_target) {
        last_ms = now;
        last_changes = dcb_status.mode_changes;
        last_target = dcb_status.spi_target;
        ctrl_status();
    }
}

// ---------------------------------------------------------------------------
int main(void) {
    // 250 MHz for the W5500 read deadline (see config.h). 1.15 V core is the
    // usual setting for this clock; the binary runs from RAM so flash speed
    // does not matter after boot.
    vreg_set_voltage(VREG_VOLTAGE_1_15);
    sleep_ms(2);
    set_sys_clock_khz(SYS_CLOCK_KHZ, true);

    gpio_init(PIN_LED);
    gpio_set_dir(PIN_LED, GPIO_OUT);

    usb_descriptors_init();
    dcbus_init();
    sd_link_init(&dcb_sd, &disk_io);
    dcb_settings_t st;
    if (settings_load(&st)) {                       // saved power-on mode
        dcb_status.no_flow = st.noflow;
        apply_force(st.force, st.cable, st.baud);
    }
    multicore_launch_core1(dcbus_core1_main);

    tud_init(0);

    for (;;) {
        tud_task();
        uart_pump();
        net_pump();
        disk_pump();
        ctrl_pump();
        // LED: off = sense, on = UART, blinking = SPI traffic
        uint32_t now = to_ms_since_boot(get_absolute_time());
        bool spi_active = now - dcb_status.last_activity_ms < 200;
        gpio_put(PIN_LED, dcb_status.mode == DCB_MODE_UART ? 1 : (spi_active ? (now >> 6) & 1 : 0));
    }
}
