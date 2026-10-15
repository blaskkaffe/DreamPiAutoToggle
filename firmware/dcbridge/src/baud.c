// Auto-baud: snap a measured bit time to a rate the Dreamcast SCIF can make.
// KOS: SCBRR2 = 50000000 / (32 * baud) - 1 (integer maths, CKS = 0), so the
// real bit time is always 640 ns * (SCBRR2 + 1). E.g. KOS "115200" is really
// 50e6 / (32 * 13) = 120192 baud; matching that exactly avoids the 4 % error a
// plain 115200 UART would have.
#include <stdint.h>
#include "dcbus.h"

#define SCIF_TICK_NS 640u     // 32 / 50 MHz

uint32_t dcbus_snap_baud(uint32_t min_low_ns, uint32_t *bit_ns_out) {
    if (min_low_ns < SCIF_TICK_NS / 2) return 0;              // shorter than any SCIF bit
    uint32_t n1 = (min_low_ns + SCIF_TICK_NS / 2) / SCIF_TICK_NS;   // SCBRR2 + 1
    if (n1 < 1 || n1 > 256) return 0;
    uint32_t bit_ns = n1 * SCIF_TICK_NS;
    uint32_t err = min_low_ns > bit_ns ? min_low_ns - bit_ns : bit_ns - min_low_ns;
    // Tolerate 15 % (edge-detection jitter is ~10 ns, so this is generous)
    if (err * 100 > bit_ns * 15) return 0;
    if (bit_ns_out) *bit_ns_out = bit_ns;
    return 50000000u / (32u * n1);
}
