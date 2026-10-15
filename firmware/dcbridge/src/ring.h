// Single-producer / single-consumer byte rings shared between core0 and core1.
#pragma once
#include <stdint.h>
#include <stdbool.h>

#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
#include "hardware/sync.h"
#define DCB_BARRIER() __dmb()
#else
#define DCB_BARRIER() __sync_synchronize()
#endif

typedef struct {
    uint8_t *buf;
    uint32_t mask;            // size - 1, size is a power of two
    volatile uint32_t head;   // written by producer only
    volatile uint32_t tail;   // written by consumer only
} ring_t;

static inline void ring_init(ring_t *r, uint8_t *buf, uint32_t size) {
    r->buf = buf; r->mask = size - 1; r->head = r->tail = 0;
}
static inline uint32_t ring_used(const ring_t *r) { return r->head - r->tail; }
static inline uint32_t ring_free(const ring_t *r) { return r->mask + 1 - ring_used(r); }

static inline bool ring_put(ring_t *r, uint8_t b) {
    uint32_t h = r->head;
    if (h - r->tail > r->mask) return false;
    r->buf[h & r->mask] = b;
    DCB_BARRIER();
    r->head = h + 1;
    return true;
}

static inline bool ring_get(ring_t *r, uint8_t *b) {
    uint32_t t = r->tail;
    if (t == r->head) return false;
    DCB_BARRIER();
    *b = r->buf[t & r->mask];
    DCB_BARRIER();
    r->tail = t + 1;
    return true;
}

// Contiguous readable span (for bulk copies into USB buffers)
static inline uint32_t ring_peek_span(const ring_t *r, const uint8_t **p) {
    uint32_t t = r->tail, used = r->head - t, off = t & r->mask;
    uint32_t span = r->mask + 1 - off;
    DCB_BARRIER();
    *p = &r->buf[off];
    return used < span ? used : span;
}
static inline void ring_consume(ring_t *r, uint32_t n) {
    DCB_BARRIER();
    r->tail += n;
}
