#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#define CFG_TUSB_RHPORT0_MODE   OPT_MODE_DEVICE
#define CFG_TUSB_OS             OPT_OS_PICO
#define CFG_TUD_ENDPOINT0_SIZE  64

#ifndef CFG_TUSB_MEM_SECTION
#define CFG_TUSB_MEM_SECTION
#endif
#ifndef CFG_TUSB_MEM_ALIGN
#define CFG_TUSB_MEM_ALIGN      __attribute__((aligned(4)))
#endif

// --- Composite device -------------------------------------------------------
//  IF0+1  CDC #0  "dcbridge UART"    -> /dev/dcbridge-uart  (PPP over SCIF)
//  IF2+3  CDC #1  "dcbridge control" -> /dev/dcbridge-ctl   (status JSON, commands)
//  IF4+5  CDC-ECM "dcbridge net"     -> dcnet0              (virtual W5500 wire)
//  IF6+7  CDC #2  "dcbridge disk"    -> /dev/dcbridge-disk  (virtual SD card sectors)
#define CFG_TUD_CDC             3
#define CFG_TUD_MSC             0
#define CFG_TUD_HID             0
#define CFG_TUD_MIDI            0
#define CFG_TUD_VENDOR          0

// The ECM/RNDIS driver; our descriptor only advertises ECM, which Linux binds
// with cdc_ether (no RNDIS: it is Windows-only and being dropped from Linux).
#define CFG_TUD_ECM_RNDIS       1
#define CFG_TUD_NCM             0

#define CFG_TUD_CDC_RX_BUFSIZE  2048
#define CFG_TUD_CDC_TX_BUFSIZE  2048
#define CFG_TUD_CDC_EP_BUFSIZE  64

#ifdef __cplusplus
}
#endif
