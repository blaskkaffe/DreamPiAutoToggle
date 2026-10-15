// Composite USB descriptors: 3x CDC-ACM + CDC-ECM.
#include <string.h>
#include "tusb.h"
#include "pico/unique_id.h"
#include "config.h"
#include "usb_descriptors.h"

// ---------------------------------------------------------------------------
// Device descriptor. IAD class triple is required for composite CDC devices.
// ---------------------------------------------------------------------------
static const tusb_desc_device_t desc_device = {
    .bLength            = sizeof(tusb_desc_device_t),
    .bDescriptorType    = TUSB_DESC_DEVICE,
    .bcdUSB             = 0x0200,
    .bDeviceClass       = TUSB_CLASS_MISC,
    .bDeviceSubClass    = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol    = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0    = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor           = USB_VID,
    .idProduct          = USB_PID,
    .bcdDevice          = USB_BCD,
    .iManufacturer      = STRID_MANUFACTURER,
    .iProduct           = STRID_PRODUCT,
    .iSerialNumber      = STRID_SERIAL,
    .bNumConfigurations = 1,
};

const uint8_t *tud_descriptor_device_cb(void) {
    return (const uint8_t *)&desc_device;
}

// ---------------------------------------------------------------------------
// Configuration descriptor
// Endpoint plan (RP2040 has 15 IN + 15 OUT, numbers can be shared IN/OUT):
//   CDC0: notif 0x81, data OUT 0x02 / IN 0x82
//   CDC1: notif 0x83, data OUT 0x04 / IN 0x84
//   ECM : notif 0x85, data OUT 0x06 / IN 0x86
//   CDC2: notif 0x87, data OUT 0x08 / IN 0x88
// ---------------------------------------------------------------------------
#define EPNUM_CDC0_NOTIF  0x81
#define EPNUM_CDC0_OUT    0x02
#define EPNUM_CDC0_IN     0x82
#define EPNUM_CDC1_NOTIF  0x83
#define EPNUM_CDC1_OUT    0x04
#define EPNUM_CDC1_IN     0x84
#define EPNUM_NET_NOTIF   0x85
#define EPNUM_NET_OUT     0x06
#define EPNUM_NET_IN      0x86
#define EPNUM_CDC2_NOTIF  0x87
#define EPNUM_CDC2_OUT    0x08
#define EPNUM_CDC2_IN     0x88

#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + 3 * TUD_CDC_DESC_LEN + TUD_CDC_ECM_DESC_LEN)

static const uint8_t desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),

    TUD_CDC_DESCRIPTOR(ITF_NUM_CDC_UART, STRID_CDC_UART, EPNUM_CDC0_NOTIF, 8,
                       EPNUM_CDC0_OUT, EPNUM_CDC0_IN, 64),
    TUD_CDC_DESCRIPTOR(ITF_NUM_CDC_CTRL, STRID_CDC_CTRL, EPNUM_CDC1_NOTIF, 8,
                       EPNUM_CDC1_OUT, EPNUM_CDC1_IN, 64),
    TUD_CDC_ECM_DESCRIPTOR(ITF_NUM_NET, STRID_NET, STRID_MAC, EPNUM_NET_NOTIF, 64,
                           EPNUM_NET_OUT, EPNUM_NET_IN, CFG_TUD_NET_ENDPOINT_SIZE,
                           CFG_TUD_NET_MTU),
    TUD_CDC_DESCRIPTOR(ITF_NUM_CDC_DISK, STRID_CDC_DISK, EPNUM_CDC2_NOTIF, 8,
                       EPNUM_CDC2_OUT, EPNUM_CDC2_IN, 64),
};
_Static_assert(sizeof(desc_configuration) == CONFIG_TOTAL_LEN, "config length");

const uint8_t *tud_descriptor_configuration_cb(uint8_t index) {
    (void)index;
    return desc_configuration;
}

// ---------------------------------------------------------------------------
// Strings. Interface strings are what the Pi's udev rules match on.
// ---------------------------------------------------------------------------
static const char *const string_desc[] = {
    [STRID_LANGID]       = NULL,              // handled specially
    [STRID_MANUFACTURER] = "dcbridge",
    [STRID_PRODUCT]      = "dcbridge Dreamcast serial bridge",
    [STRID_SERIAL]       = NULL,              // flash unique ID
    [STRID_CDC_UART]     = "dcbridge UART",
    [STRID_CDC_CTRL]     = "dcbridge control",
    [STRID_NET]          = "dcbridge net",
    [STRID_MAC]          = NULL,              // from tud_network_mac_address
    [STRID_CDC_DISK]     = "dcbridge disk",
};

// Host-side MAC of the usb0 interface (locally administered, unicast).
// The Dreamcast's own MAC is whatever KOS writes into the virtual SHAR register.
uint8_t tud_network_mac_address[6] = {0x02, 0xDC, 0x00, 0x00, 0x00, 0x01};

void usb_descriptors_init(void) {
    // Derive the last 3 MAC bytes from the flash unique ID so two bridges
    // on one Pi do not collide.
    pico_unique_board_id_t id;
    pico_get_unique_board_id(&id);
    tud_network_mac_address[3] = id.id[5];
    tud_network_mac_address[4] = id.id[6];
    tud_network_mac_address[5] = id.id[7];
}

static uint16_t desc_str[33];

static uint8_t put_ascii(const char *s) {
    uint8_t n = (uint8_t)strlen(s);
    if (n > 32) n = 32;
    for (uint8_t i = 0; i < n; i++) desc_str[1 + i] = (uint8_t)s[i];
    return n;
}

const uint16_t *tud_descriptor_string_cb(uint8_t index, uint16_t langid) {
    (void)langid;
    uint8_t chr_count;
    char buf[2 * PICO_UNIQUE_BOARD_ID_SIZE_BYTES + 1];

    switch (index) {
    case STRID_LANGID:
        desc_str[1] = 0x0409;
        chr_count = 1;
        break;
    case STRID_SERIAL:
        pico_get_unique_board_id_string(buf, sizeof buf);
        chr_count = put_ascii(buf);
        break;
    case STRID_MAC: {
        static const char hex[] = "0123456789ABCDEF";
        for (int i = 0; i < 6; i++) {
            desc_str[1 + 2 * i]     = hex[tud_network_mac_address[i] >> 4];
            desc_str[1 + 2 * i + 1] = hex[tud_network_mac_address[i] & 0xF];
        }
        chr_count = 12;
        break;
    }
    default:
        if (index >= sizeof(string_desc) / sizeof(string_desc[0]) || !string_desc[index])
            return NULL;
        chr_count = put_ascii(string_desc[index]);
        break;
    }
    desc_str[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2 * chr_count + 2));
    return desc_str;
}

// TinyUSB's combined ECM/RNDIS driver references the RNDIS message handler
// (normally lib/networking/rndis_reports.c, which drags in lwIP). Our
// descriptor only offers ECM, so this is unreachable; a stub keeps the link
// clean without lwIP.
void rndis_class_set_handler(uint8_t *data, int size) { (void)data; (void)size; }
