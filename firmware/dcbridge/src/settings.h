// Boot-time settings kept in the last 4 KB sector of flash ("mode ... save").
#pragma once
#include <stdint.h>
#include <stdbool.h>

typedef struct {
    uint8_t  force;        // dcb_force_t
    uint8_t  cable;        // UART baud follows the USB host
    uint8_t  noflow;       // ignore the Dreamcast's RTS
    uint32_t baud;         // fixed UART rate (0 = auto / host)
} dcb_settings_t;

bool settings_load(dcb_settings_t *s);         // false if nothing valid stored
bool settings_save(const dcb_settings_t *s);   // core0 only; ~50 ms with IRQs off
