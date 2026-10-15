#pragma once

enum {
    ITF_NUM_CDC_UART = 0,   // + data interface 1
    ITF_NUM_CDC_UART_DATA,
    ITF_NUM_CDC_CTRL,       // + data interface 3
    ITF_NUM_CDC_CTRL_DATA,
    ITF_NUM_NET,            // + data interface 5
    ITF_NUM_NET_DATA,
    ITF_NUM_CDC_DISK,       // + data interface 7
    ITF_NUM_CDC_DISK_DATA,
    ITF_NUM_TOTAL
};

// CDC instance numbers as seen by tud_cdc_n_*()
#define CDC_UART 0
#define CDC_CTRL 1
#define CDC_DISK 2

enum {
    STRID_LANGID = 0,
    STRID_MANUFACTURER,
    STRID_PRODUCT,
    STRID_SERIAL,
    STRID_CDC_UART,
    STRID_CDC_CTRL,
    STRID_NET,
    STRID_MAC,
    STRID_CDC_DISK,
};

void usb_descriptors_init(void);
