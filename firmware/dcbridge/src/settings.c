#include <string.h>
#include "pico/stdlib.h"
#include "hardware/flash.h"
#include "hardware/sync.h"
#include "settings.h"

#define SETTINGS_OFFSET (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)
#define SETTINGS_MAGIC  0x44434232u          // "DCB2"

typedef struct {
    uint32_t magic;
    dcb_settings_t s;
    uint32_t check;
} stored_t;

static uint32_t checksum(const dcb_settings_t *s) {
    const uint8_t *p = (const uint8_t *)s;
    uint32_t h = 2166136261u;
    for (unsigned i = 0; i < sizeof *s; i++) h = (h ^ p[i]) * 16777619u;
    return h;
}

bool settings_load(dcb_settings_t *s) {
    const stored_t *st = (const stored_t *)(XIP_BASE + SETTINGS_OFFSET);
    stored_t copy;
    memcpy(&copy, st, sizeof copy);
    if (copy.magic != SETTINGS_MAGIC || copy.check != checksum(&copy.s)) return false;
    *s = copy.s;
    return true;
}

bool settings_save(const dcb_settings_t *s) {
    static uint8_t page[FLASH_PAGE_SIZE];
    stored_t st = { SETTINGS_MAGIC, *s, checksum(s) };
    memset(page, 0xFF, sizeof page);
    memcpy(page, &st, sizeof st);
    // The whole binary runs from RAM (copy_to_ram) and core1 never touches
    // flash, so disabling interrupts on this core is enough.
    uint32_t irq = save_and_disable_interrupts();
    flash_range_erase(SETTINGS_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(SETTINGS_OFFSET, page, FLASH_PAGE_SIZE);
    restore_interrupts(irq);
    dcb_settings_t back;
    return settings_load(&back) && !memcmp(&back, s, sizeof back);
}
