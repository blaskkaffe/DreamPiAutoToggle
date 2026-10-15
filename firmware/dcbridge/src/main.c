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

static void ctrl_status(void) {
    if (!tud_cdc_n_connected(CDC_CTRL)) return;
    char line[768];
    int n = snprintf(line, sizeof line,
        "{\"fw\":\"dcbridge-0.2\",\"uptime_ms\":%lu,\"mode\":\"%s\",\"spi\":\"%s\","
        "\"baud\":%lu,\"mode_changes\":%lu,"
        "\"uart\":{\"rx\":%lu,\"tx\":%lu,\"ferr\":%lu,\"ovf\":%lu,\"cts_holds\":%lu},"
        "\"spi_bus\":{\"bytes\":%lu,\"frames\":%lu,\"underruns\":%lu,\"sd_sessions\":%lu},"
        "\"w5500\":{\"open\":%s,\"link\":%s,\"tx\":%lu,\"rx\":%lu,\"drop_tx\":%lu,"
        "\"rx_full\":%lu,\"resets\":%lu},"
        "\"sd\":{\"daemon\":%s,\"ready\":%s,\"sessions\":%lu,\"reads\":%lu,\"writes\":%lu,"
        "\"misses\":%lu,\"crc_err\":%lu,\"busy_drops\":%lu,\"pending_writes\":%lu}}\r\n",
        (unsigned long)to_ms_since_boot(get_absolute_time()), mode_name(), target_name(),
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
            cmd_len = 0;
        } else if (cmd_len < sizeof cmd - 1) {
            cmd[cmd_len++] = c;
        }
    }
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
