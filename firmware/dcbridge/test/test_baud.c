// Host test for the SCIF baud snapper. cc -I../src test_baud.c ../src/baud.c
#include <stdio.h>
#include <assert.h>
#include "dcbus.h"

static uint32_t kos_actual(uint32_t requested) {      // what KOS really programs
    uint32_t brr = 50000000u / (32u * requested) - 1;
    return 50000000u / (32u * (brr + 1));
}

int main(void) {
    const uint32_t req[] = { 9600, 19200, 38400, 57600, 115200, 230400, 500000, 1562500 };
    for (unsigned i = 0; i < sizeof req / sizeof req[0]; i++) {
        uint32_t real = kos_actual(req[i]);
        uint32_t bit_ns = 1000000000u / real;
        // measured pulse = real bit +/- 80 ns (sync jitter, slow edges, cable)
        for (int d = -80; d <= 80; d += 20) {
            uint32_t m = (uint32_t)((int32_t)bit_ns + d);
            uint32_t got = dcbus_snap_baud(m, NULL);
            if (got != real) { printf("FAIL req %u meas %u ns -> %u (want %u)\n", req[i], m, got, real); return 1; }
        }
        printf("KOS %-7u -> SCIF really runs at %-7u : snapped OK\n", req[i], real);
    }
    assert(dcbus_snap_baud(100, NULL) == 0);       // SPI-speed pulses rejected
    // Host-requested rates (cable mode) map to what KOS really programs
    for (unsigned i = 0; i < sizeof req / sizeof req[0]; i++)
        assert(dcbus_kos_baud(req[i]) == kos_actual(req[i]) || req[i] <= 9600);
    assert(dcbus_kos_baud(9600) == 9765);           // CKS=1 tier, like scif_init()
    assert(dcbus_kos_baud(1500000) == 1562500);     // dcload-serial's "1.5M"
    puts("host baud -> SCIF rate mapping OK");
    puts("ALL BAUD TESTS PASSED");
    return 0;
}
