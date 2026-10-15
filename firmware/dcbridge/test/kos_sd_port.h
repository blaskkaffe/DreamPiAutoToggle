// Faithful port of the KallistiOS SD driver (kernel/arch/dreamcast/hardware/sd.c,
// SCIF interface) for host tests. The includer provides:
//   uint8_t xfer(uint8_t mosi);  void set_cs(int enabled);  void idle_us(uint32_t us);
#pragma once
#include <stdint.h>
#include <stddef.h>

// ---------------------------------------------------------------------------
#define CMD(n) ((n) | 0x40)
#define MAX_RETRIES 5000
#define READ_RETRIES 50000
static int byte_mode, initted;

static uint16_t net_crc16ccitt(const uint8_t *p, int n, uint16_t crc) {
    while (n--) { crc ^= (uint16_t)(*p++) << 8; for (int i = 0; i < 8; i++) crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1; }
    return crc;
}
static uint8_t sd_crc7(const uint8_t *d, int n) {
    uint8_t crc = 0;
    while (n--) { uint8_t b = *d++; for (int i = 0; i < 8; i++) { crc <<= 1; if ((b ^ crc) & 0x80) crc ^= 0x09; b <<= 1; } }
    return (uint8_t)(crc << 1);
}
static int sd_wait_ready(void) {   // 200 us spin, then thd_poll up to 500 ms
    xfer(0xFF);
    for (uint32_t i = 0; i < 500000; i++) if (xfer(0xFF) == 0xFF) return 0;
    return -1;
}
static int sd_send_cmd(uint8_t cmd, uint32_t arg) {
    uint8_t rv, pkt[6];
    int i;
    if (sd_wait_ready()) return -1;
    pkt[0] = cmd; pkt[1] = arg >> 24; pkt[2] = arg >> 16; pkt[3] = arg >> 8; pkt[4] = arg;
    pkt[5] = sd_crc7(pkt, 5) | 0x01;
    for (i = 0; i < 6; i++) xfer(pkt[i]);
    if (cmd == CMD(12)) xfer(0xFF);
    i = 0;
    do { rv = xfer(0xFF); ++i; } while ((rv & 0x80) && i < 20);
    if (rv & 0x80) return -1;
    return rv;
}
static int acmd41_loop(uint32_t arg) {
    int i = 0, rv;
    while (i++ < MAX_RETRIES) {
        if (sd_send_cmd(CMD(55), 0) > 1) return -1;
        if ((rv = sd_send_cmd(CMD(41), arg)) > 1) return -1;
        if (rv == 0) break;
        idle_us(150);                       // slow-mode byte time adds up
    }
    if (i == MAX_RETRIES + 1 || i > MAX_RETRIES) return -2;
    return 0;
}
static int sd_init(void) {
    uint8_t buf[4];
    initted = 0; byte_mode = 0;
    for (int i = 0; i < 10; ++i) xfer(0xFF);           // /CS high: not seen by the emulator
    set_cs(1);
    if (sd_send_cmd(CMD(0), 0) != 1) { set_cs(0); return -1; }
    if (sd_send_cmd(CMD(8), 0x1AA) == 1) {
        for (int i = 0; i < 4; i++) buf[i] = xfer(0xFF);
        if ((buf[2] & 0x0F) != 0x01 || buf[3] != 0xAA) { set_cs(0); return -2; }
        if (acmd41_loop(0x40000000)) { set_cs(0); return -3; }
        if (sd_send_cmd(CMD(58), 0)) { set_cs(0); return -4; }
        for (int i = 0; i < 4; i++) buf[i] = xfer(0xFF);
        if (!(buf[0] & 0x40)) byte_mode = 1;
    } else { set_cs(0); return -5; }
    if (sd_send_cmd(CMD(59), 1)) { set_cs(0); return -6; }
    set_cs(0); xfer(0xFF);
    initted = 1;
    return 0;
}
static int read_data(size_t bytes, uint8_t *buf) {
    uint8_t byte; int i = 0;
    do { byte = xfer(0xFF); ++i; } while (byte == 0xFF && i < READ_RETRIES);
    if (byte != 0xFE) return -1;
    for (size_t k = 0; k < bytes; k++) buf[k] = xfer(0xFF);
    uint16_t crc = xfer(0xFF) << 8; crc |= xfer(0xFF);
    return crc != net_crc16ccitt(buf, bytes, 0);
}
static int reinits;
static int sd_read_blocks(uint32_t block, size_t count, uint8_t *buf) {
    int rv, retried = 0;
    if (byte_mode) block <<= 9;
again:
    rv = 0; set_cs(1);
    if (count == 1) {
        if (sd_send_cmd(CMD(17), block) || read_data(512, buf)) rv = -1;
    } else {
        if (sd_send_cmd(CMD(18), block)) rv = -1;
        else {
            for (size_t i = 0; i < count; i++) if (read_data(512, buf + 512 * i)) { rv = -1; break; }
            if (!rv) sd_send_cmd(CMD(12), 0);
        }
    }
    set_cs(0);
    if (rv && !retried) { retried = 1; reinits++; if (!sd_init()) goto again; }
    xfer(0xFF);
    return rv;
}
static int write_data(uint8_t tag, size_t bytes, const uint8_t *buf) {
    if (sd_wait_ready()) return -1;
    xfer(tag);
    uint16_t crc = net_crc16ccitt(buf, bytes, 0);
    for (size_t i = 0; i < bytes; i++) xfer(buf[i]);
    xfer(crc >> 8); xfer(crc);
    uint8_t rv = xfer(0xFF);
    return ((rv & 0x1F) != 0x05) ? -1 : 0;
}
static int sd_write_blocks(uint32_t block, size_t count, const uint8_t *buf) {
    int rv, retried = 0;
    if (byte_mode) block <<= 9;
again:
    rv = 0; set_cs(1);
    if (count == 1) {
        if (sd_send_cmd(CMD(24), block) || write_data(0xFE, 512, buf)) rv = -1;
    } else {
        sd_send_cmd(CMD(55), 0); sd_send_cmd(CMD(23), count);
        if (sd_send_cmd(CMD(25), block)) rv = -1;
        else {
            for (size_t i = 0; i < count; i++) if (write_data(0xFC, 512, buf + 512 * i)) { rv = -1; break; }
            if (sd_wait_ready()) rv = -1; else xfer(0xFD);
        }
    }
    set_cs(0);
    if (rv && !retried) { retried = 1; reinits++; if (!sd_init()) goto again; }
    xfer(0xFF);
    return rv;
}
static uint64_t sd_get_size(void) {
    uint8_t csd[16]; uint64_t rv;
    set_cs(1);
    if (sd_send_cmd(CMD(9), 0) || read_data(16, csd)) rv = (uint64_t)-1;
    else if ((csd[0] >> 6) == 1)
        rv = ((((uint64_t)csd[9]) | (uint64_t)(csd[8] << 8) | ((uint64_t)(csd[7] & 0x3F) << 16)) + 1) << 19;
    else rv = (uint64_t)-2;
    set_cs(0); xfer(0xFF);
    return rv;
}

