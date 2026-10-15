#include <string.h>
#include "sd_emu.h"
#include "ring.h"      // DCB_BARRIER

enum {
    S_IDLE = 0,     // between commands (MOSI 0xFF polls)
    S_CMD,          // collecting a 6-byte command
    S_READ,         // CMD17/18/9: waiting for data or streaming blocks
    S_W_TOKEN,      // CMD24/25: waiting for the data token
    S_W_DATA,
    S_W_CRC1,
    S_W_CRC2,
};

#define R1_IDLE     0x01
#define R1_ILLEGAL  0x04
#define DR_ACCEPTED 0xE5    // data response xxx0 010 1
#define DR_CRC_ERR  0xEB    // data response xxx0 101 1
#define REQUEST_RETRY_MS 25

static uint16_t crc16_tab[256];

static inline uint16_t crc16_upd(uint16_t crc, uint8_t b) {
    return (uint16_t)((crc << 8) ^ crc16_tab[((crc >> 8) ^ b) & 0xFF]);
}

uint16_t sd_crc16(const uint8_t *p, uint32_t n) {
    uint16_t crc = 0;
    while (n--) crc = crc16_upd(crc, *p++);
    return crc;
}

static uint8_t crc7(const uint8_t *p, int n) {
    uint8_t crc = 0;
    while (n--) {
        uint8_t d = *p++;
        for (int i = 0; i < 8; i++) {
            crc <<= 1;
            if ((d ^ crc) & 0x80) crc ^= 0x09;
            d <<= 1;
        }
    }
    return (uint8_t)((crc << 1) | 1);
}

void sd_emu_init(sd_emu_t *e) {
    memset(e, 0, sizeof *e);
    for (int i = 0; i < 256; i++) {
        uint16_t c = (uint16_t)(i << 8);
        for (int j = 0; j < 8; j++) c = (uint16_t)((c & 0x8000) ? (c << 1) ^ 0x1021 : c << 1);
        crc16_tab[i] = c;
    }
    for (uint32_t i = 0; i < SD_CACHE_N; i++) e->cache[i].lba = SD_LBA_NONE;
}

// ---------------------------------------------------------------------------
// Output queue (bytes for MISO, pulled by the glue into the PIO TX FIFO)
// ---------------------------------------------------------------------------
static inline void put(sd_emu_t *e, uint8_t b) {
    if (e->out_wr < SD_OUT_MAX) e->out[e->out_wr++] = b;
}

static inline bool out_empty(const sd_emu_t *e) {
    return e->out_rd == e->out_wr && !e->src_left && e->tail_rd == e->tail_n;
}

static inline void out_clear(sd_emu_t *e) {
    e->out_rd = e->out_wr = 0;
    e->src_left = 0;
    e->tail_rd = e->tail_n = 0;
}

bool DCB_RAMFUNC(sd_emu_pull)(sd_emu_t *e, uint8_t *b) {
    if (e->out_rd != e->out_wr) {
        *b = e->out[e->out_rd++];
        if (e->out_rd == e->out_wr) e->out_rd = e->out_wr = 0;
        return true;
    }
    if (e->src_left) {
        *b = *e->src++;
        e->src_left--;
        return true;
    }
    if (e->tail_rd != e->tail_n) {
        *b = e->tail[e->tail_rd++];
        if (e->tail_rd == e->tail_n) {
            e->tail_rd = e->tail_n = 0;
            // If core0 rewrote the entry mid-stream the Dreamcast got a torn
            // sector with the old CRC: it will see the CRC error and retry.
            if (e->src_seq && *e->src_seq != e->src_seq0) e->st_torn++;
            e->src_seq = 0;
        }
        return true;
    }
    return false;
}

static void put_block(sd_emu_t *e, const uint8_t *p, uint16_t n) {
    put(e, 0xFF);                   // Nac
    put(e, 0xFE);                   // start block token
    for (uint16_t i = 0; i < n; i++) put(e, p[i]);
    uint16_t crc = sd_crc16(p, n);
    put(e, (uint8_t)(crc >> 8));
    put(e, (uint8_t)crc);
}

// ---------------------------------------------------------------------------
// Sector lookup: newest unacked write first, then the direct-mapped cache.
// Returns a pointer to stream from; no copying on core1.
// ---------------------------------------------------------------------------
static bool DCB_RAMFUNC(lookup)(sd_emu_t *e, uint32_t lba) {
    uint32_t t = e->w_tail;
    for (uint32_t i = e->w_head; i != t;) {
        i--;
        const sd_wslot_t *s = &e->wslot[i & (SD_WSLOTS - 1)];
        if (s->lba == lba) {           // slots are only ever rewritten by core1 itself
            e->src = s->data;
            e->tail[0] = (uint8_t)(s->crc >> 8);
            e->tail[1] = (uint8_t)s->crc;
            e->src_seq = 0;
            return true;
        }
    }
    sd_cache_t *c = &e->cache[lba & (SD_CACHE_N - 1)];
    uint32_t s1 = c->seq;
    if ((s1 & 1) || c->lba != lba) return false;
    DCB_BARRIER();
    uint16_t crc = c->crc;
    DCB_BARRIER();
    if (c->seq != s1) return false;
    e->src = c->data;
    e->tail[0] = (uint8_t)(crc >> 8);
    e->tail[1] = (uint8_t)crc;
    e->src_seq = &c->seq;
    e->src_seq0 = s1;
    return true;
}

static void post_request(sd_emu_t *e, uint32_t lba) {
    uint32_t h = e->rq_head;
    if (h - e->rq_tail >= SD_RQ_N) return;      // core0 is behind; we retry anyway
    e->rq[h & (SD_RQ_N - 1)] = lba;
    DCB_BARRIER();
    e->rq_head = h + 1;
}

// Try to queue the next data block of a pending read.
static void DCB_RAMFUNC(try_fill)(sd_emu_t *e) {
    if (e->state != S_READ || !out_empty(e)) return;
    uint32_t gen = e->cache_gen;
    bool retry_due = (uint32_t)(e->now_ms - e->req_ms) >= REQUEST_RETRY_MS;
    if (gen == e->seen_gen && !retry_due) return;      // nothing new since last miss
    e->seen_gen = gen;

    if (!lookup(e, e->rd_lba)) {
        if (retry_due) {
            post_request(e, e->rd_lba);
            e->req_ms = e->now_ms;
            e->st_misses++;
        }
        return;
    }
    if (!e->first_block) { put(e, 0xFF); put(e, 0xFF); }   // gap: lets CMD12's wait_ready see 0xFF
    put(e, 0xFE);
    e->src_left = SD_SECTOR;
    e->tail_rd = 0;
    e->tail_n = 2;

    if (e->multi) {
        e->rd_lba++;
        e->first_block = false;
        if ((e->rd_lba % SD_PREFETCH) == 0) post_request(e, e->rd_lba + SD_PREFETCH);  // read-ahead hint
        e->seen_gen = e->cache_gen - 1;      // look for the next block on the next poll
    } else {
        e->state = S_IDLE;
    }
}

// ---------------------------------------------------------------------------
// Commands (the set KallistiOS sd.c uses, plus a few harmless extras)
// ---------------------------------------------------------------------------
static void build_csd(const sd_emu_t *e, uint8_t csd[16]) {
    uint32_t c_size = e->sectors ? e->sectors / 1024u - 1u : 0;    // units of 512 KiB
    const uint8_t t[16] = { 0x40, 0x0E, 0x00, 0x32, 0x5B, 0x59, 0x00,
        (uint8_t)((c_size >> 16) & 0x3F), (uint8_t)(c_size >> 8), (uint8_t)c_size,
        0x7F, 0x80, 0x0A, 0x40, 0x00, 0x00 };
    memcpy(csd, t, 16);
    csd[15] = crc7(csd, 15);
}

static void build_cid(uint8_t cid[16]) {
    const uint8_t t[16] = { 0x00, 'D', 'C', 'd', 'c', 'b', 'r', 'g', 0x10,
                            0x00, 0x00, 0x00, 0x01, 0x01, 0x9A, 0x00 };
    memcpy(cid, t, 16);
    cid[15] = crc7(cid, 15);
}

static void DCB_RAMFUNC(exec_cmd)(sd_emu_t *e) {
    uint8_t c = e->cmd[0] & 0x3F;
    uint32_t arg = (uint32_t)e->cmd[1] << 24 | (uint32_t)e->cmd[2] << 16 |
                   (uint32_t)e->cmd[3] << 8 | e->cmd[4];
    bool app = e->app_cmd;
    e->app_cmd = false;
    e->state = S_IDLE;
    e->st_cmds++;
    uint8_t r1 = e->initialized ? 0x00 : R1_IDLE;

    if (app && c == 41) goto init_poll;
    if (app && c == 23) { put(e, r1); return; }        // ACMD23: pre-erase count

    switch (c) {
    case 0:                                           // GO_IDLE: a new session
        e->initialized = false;
        // How long the bus was silent before this init. A cold boot shows
        // seconds; KOS's retry-after-error re-init shows ~0. The Pi only
        // applies queued edits for the former (the FAT is not mounted then).
        e->session_idle_ms = e->idle_before_ms;
        e->idle_before_ms = 0;
        DCB_BARRIER();
        e->session_req++;
        e->st_sessions++;
        put(e, R1_IDLE);
        return;
    case 1:
    init_poll:                                        // ACMD41 / CMD1: ready once the Pi is
        if (!e->initialized && e->session_ready == e->session_req && e->sectors)
            e->initialized = true;
        put(e, e->initialized ? 0x00 : R1_IDLE);
        return;
    case 8:                                           // SEND_IF_COND: echo pattern
        put(e, r1); put(e, 0); put(e, 0);
        put(e, (uint8_t)((arg >> 8) & 0x0F)); put(e, (uint8_t)arg);
        return;
    case 55: e->app_cmd = true; put(e, r1); return;
    case 58:                                          // READ_OCR: powered up, SDHC
        put(e, r1);
        put(e, e->initialized ? 0xC0 : 0x40); put(e, 0xFF); put(e, 0x80); put(e, 0x00);
        return;
    case 16: case 59: put(e, r1); return;
    case 13: put(e, r1); put(e, 0x00); return;
    case 9:  { uint8_t b[16]; build_csd(e, b); put(e, r1); put_block(e, b, 16); return; }
    case 10: { uint8_t b[16]; build_cid(b);    put(e, r1); put_block(e, b, 16); return; }
    case 12:                                          // STOP_TRANSMISSION: stuff byte, then R1
        put(e, 0xFF); put(e, r1);
        return;
    case 17: case 18:
        if (!e->initialized) break;
        put(e, 0x00);
        e->rd_lba = arg;
        e->multi = (c == 18);
        e->first_block = true;
        e->state = S_READ;
        e->seen_gen = e->cache_gen - 1;
        e->req_ms = e->now_ms - REQUEST_RETRY_MS;
        e->st_reads++;
        return;
    case 24: case 25:
        if (!e->initialized) break;
        put(e, 0x00);
        e->wr_lba = arg;
        e->multi = (c == 25);
        e->state = S_W_TOKEN;
        return;
    default:
        break;
    }
    put(e, r1 | R1_ILLEGAL);
}

void DCB_RAMFUNC(sd_emu_on_byte)(sd_emu_t *e, uint8_t in) {
    uint32_t gap = e->now_ms - e->last_activity_ms;
    if (gap > 50) e->idle_before_ms = gap;          // remembered for the next CMD0
    e->last_activity_ms = e->now_ms;
    switch (e->state) {
    case S_CMD:
        e->cmd[e->cmd_n++] = in;
        if (e->cmd_n == 6) exec_cmd(e);
        return;

    case S_W_TOKEN:
        if (in == 0xFF) return;                       // wait_ready polling
        if (e->multi && in == 0xFD) { e->state = S_IDLE; return; }   // stop tran
        if (in == (e->multi ? 0xFC : 0xFE)) {
            if (e->w_head - e->w_tail >= SD_WSLOTS) { e->st_busy++; e->state = S_IDLE; return; }
            e->wpos = 0;
            e->wcrc = 0;
            e->state = S_W_DATA;
            return;
        }
        break;                                        // maybe a new command

    case S_W_DATA: {
        sd_wslot_t *s = &e->wslot[e->w_head & (SD_WSLOTS - 1)];
        s->data[e->wpos++] = in;
        e->wcrc = crc16_upd(e->wcrc, in);
        if (e->wpos == SD_SECTOR) e->state = S_W_CRC1;
        return;
    }
    case S_W_CRC1:
        e->crc_hi = in;
        e->state = S_W_CRC2;
        return;

    case S_W_CRC2: {
        // KOS reads the data response with a single read right after the CRC,
        // so this byte must be queued immediately (same deadline as a W5500 read).
        if ((uint16_t)(e->crc_hi << 8 | in) == e->wcrc) {
            put(e, DR_ACCEPTED);
            sd_wslot_t *s = &e->wslot[e->w_head & (SD_WSLOTS - 1)];
            s->lba = e->wr_lba++;
            s->crc = e->wcrc;
            DCB_BARRIER();
            e->w_head++;
            e->st_writes++;
        } else {
            put(e, DR_CRC_ERR);
            e->st_crc_err++;
        }
        e->state = e->multi ? S_W_TOKEN : S_IDLE;
        return;
    }
    default:
        break;
    }

    // IDLE, READ or W_TOKEN: anything that is not a poll byte starts a command.
    // Stale stream bytes still in the PIO FIFO (<= 4) drain during the
    // remaining 5 command bytes, which the Dreamcast ignores.
    if ((in & 0xC0) == 0x40) {
        out_clear(e);
        e->cmd[0] = in;
        e->cmd_n = 1;
        e->state = S_CMD;
    }
}

void DCB_RAMFUNC(sd_emu_poll)(sd_emu_t *e) {
    try_fill(e);
}

void sd_emu_frame_end(sd_emu_t *e) {
    if (e->state != S_IDLE) e->state = S_IDLE;     // abandons partial commands/blocks
    e->cmd_n = 0;
    out_clear(e);
}

uint8_t DCB_RAMFUNC(sd_emu_filler)(const sd_emu_t *e) {
    // Busy (0x00) only while waiting for a write token with no free slot:
    // KOS always polls for 0xFF before sending a token or a command.
    if (e->state == S_W_TOKEN && e->w_head - e->w_tail >= SD_WSLOTS) return 0x00;
    return 0xFF;
}

// ---------------------------------------------------------------------------
// core0 backend
// ---------------------------------------------------------------------------
void sd_be_cache_put(sd_emu_t *e, uint32_t lba, const uint8_t *data) {
    sd_cache_t *c = &e->cache[lba & (SD_CACHE_N - 1)];
    c->seq++;
    DCB_BARRIER();
    c->lba = lba;
    memcpy(c->data, data, SD_SECTOR);
    c->crc = sd_crc16(data, SD_SECTOR);
    DCB_BARRIER();
    c->seq++;
    DCB_BARRIER();
    e->cache_gen++;
}

void sd_be_invalidate(sd_emu_t *e) {
    for (uint32_t i = 0; i < SD_CACHE_N; i++) {
        sd_cache_t *c = &e->cache[i];
        c->seq++;
        DCB_BARRIER();
        c->lba = SD_LBA_NONE;
        DCB_BARRIER();
        c->seq++;
    }
    e->cache_gen++;
}

bool sd_be_cached(const sd_emu_t *e, uint32_t lba) {
    return e->cache[lba & (SD_CACHE_N - 1)].lba == lba;
}

bool sd_be_pop_request(sd_emu_t *e, uint32_t *lba) {
    uint32_t t = e->rq_tail;
    if (t == e->rq_head) return false;
    DCB_BARRIER();
    *lba = e->rq[t & (SD_RQ_N - 1)];
    DCB_BARRIER();
    e->rq_tail = t + 1;
    return true;
}

uint32_t sd_be_writes_pending(const sd_emu_t *e) { return e->w_head - e->w_tail; }

const sd_wslot_t *sd_be_write_slot(const sd_emu_t *e, uint32_t index) {
    return &e->wslot[index & (SD_WSLOTS - 1)];
}

void sd_be_write_acked(sd_emu_t *e) {
    uint32_t t = e->w_tail;
    if (t == e->w_head) return;
    const sd_wslot_t *s = &e->wslot[t & (SD_WSLOTS - 1)];
    sd_be_cache_put(e, s->lba, s->data);   // cache first, so reads never miss it
    DCB_BARRIER();
    e->w_tail = t + 1;
}

void sd_be_session_ready(sd_emu_t *e, uint32_t session, uint32_t sectors, bool invalidate) {
    if (invalidate || sectors != e->sectors) sd_be_invalidate(e);
    e->sectors = sectors;
    DCB_BARRIER();
    e->session_ready = session;
}
