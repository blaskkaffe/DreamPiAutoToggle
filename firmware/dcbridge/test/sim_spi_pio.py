#!/usr/bin/env python3
"""Cycle-level check of the dc_spi_slave PIO program against the KOS
scif-spi.c bit-bang timing, with a model of core1's response latency.

Answers: how many core1 cycles (at 250 MHz) may pass between the W5500 control
byte landing in the RX FIFO and the first read byte being pushed, before the
Dreamcast samples filler instead of data?

Instruction words are parsed from the pioasm-generated header, so this tests
the program that actually ships."""
import re, sys, itertools

HDR = sys.argv[1] if len(sys.argv) > 1 else "../build/dcbus.pio.h"
src = open(HDR).read()
blk = re.search(r"dc_spi_slave_program_instructions\[\] = \{(.*?)\};", src, re.S).group(1)
PROG = [int(x, 16) for x in re.findall(r"0x([0-9a-f]{4}),", blk)]
WRAP_T = int(re.search(r"dc_spi_slave_wrap_target (\d+)", src).group(1))
WRAP = int(re.search(r"dc_spi_slave_wrap (\d+)", src).group(1))
CYCLE_NS = 4.0  # 250 MHz

MOSI, MISO, SCLK, CS = 0, 1, 2, 3


class SM:
    def __init__(self, filler=0x00):
        self.pc = WRAP_T; self.x = self.y = 0; self.osr = 0; self.osr_cnt = 32
        self.isr = 0; self.isr_cnt = 0; self.txf = []; self.rxf = []
        self.miso = 1; self.irq0 = False
        prog = list(PROG)
        # patch filler like set_filler()
        prog[3] = 0xe000 | (filler >> 7)
        prog[8] = 0xa0eb if filler else 0xa0e3   # mov osr, ~null / null
        self.prog = prog

    def step(self, pins):            # pins: synchronized input levels (dict)
        ins = self.prog[self.pc]; op = ins >> 13; arg1 = (ins >> 5) & 7; arg2 = ins & 0x1f
        nxt = self.pc + 1 if self.pc != WRAP else WRAP_T
        if op == 0:      # JMP
            cond, addr = arg1, arg2
            take = {0: True, 1: self.x == 0, 2: self.x != 0, 4: self.y == 0, 5: self.y != 0,
                    6: pins[SCLK] == 1}.get(cond)
            if cond == 2:
                take = self.x != 0; self.x = (self.x - 1) & 0xffffffff
            if cond == 4 + 0 and False: pass
            if cond == 4:  # y-- per pioasm encoding (100 = Y--)
                take = self.y != 0; self.y = (self.y - 1) & 0xffffffff
            if cond == 3: take = False
            self.pc = addr if take else nxt; return
        if op == 1:      # WAIT pol src idx
            pol = (ins >> 7) & 1; srcsel = (ins >> 5) & 3; idx = ins & 0x1f
            assert srcsel == 1
            if pins[idx] == pol: self.pc = nxt
            return
        if op == 2:      # IN pins, 1
            self.isr = ((self.isr << 1) | pins[MOSI]) & 0xff; self.isr_cnt += 1
            if self.isr_cnt == 8: self.rxf.append(self.isr); self.isr = 0; self.isr_cnt = 0
            self.pc = nxt; return
        if op == 3:      # OUT dest, 1
            bit = (self.osr >> 31) & 1; self.osr = (self.osr << 1) & 0xffffffff
            if arg1 == 0: self.miso = bit
            self.pc = nxt; return
        if op == 4:      # PULL
            if self.txf: self.osr = self.txf.pop(0) << 24; self.pc = nxt
            return
        if op == 5:      # MOV dst, (op) src
            dst = arg1; mop = (ins >> 3) & 3; s = ins & 7
            val = {3: 0, 5: 0xffffffff if len(self.txf) < 1 else 0, 1: self.x}[s]
            if mop == 1: val ^= 0xffffffff
            if dst == 1: self.x = val
            elif dst == 7: self.osr = val
            else: raise Exception(hex(ins))
            self.pc = nxt; return
        if op == 6:      # IRQ
            self.irq0 = True; self.pc = nxt; return
        if op == 7:      # SET
            if arg1 == 0: self.miso = arg2 & 1
            elif arg1 == 2: self.y = arg2
            else: raise Exception(hex(ins))
            self.pc = nxt; return
        raise Exception(hex(ins))


def kos_read_frame(access, gap, header, nread):
    """Edge list for: set_cs(1); write_data(header); read_byte() x nread.
    Each SCSPTR2 access takes `access` ns. Returns events and sample times."""
    t = 100.0; ev = [(0, CS, 1), (0, SCLK, 0), (0, MOSI, 0)]; samples = []
    ev.append((t, CS, 0)); t += access + gap
    for b in header:            # scif_spi_write_byte
        for i in range(7, -1, -1):
            bit = (b >> i) & 1
            ev += [(t, MOSI, bit), (t, SCLK, 0)]; t += access
            ev.append((t, SCLK, 1)); t += access
        ev.append((t, SCLK, 0)); ev.append((t, MOSI, 0)); t += access
    t += gap                    # return from write_data, call read_byte
    for _ in range(nread):      # scif_spi_read_byte: low, high, read
        for i in range(8):
            ev += [(t, SCLK, 0), (t, MOSI, 1)]; t += access
            ev.append((t, SCLK, 1)); t += access
            samples.append(t); t += access       # the read of SCSPTR2
        t += gap / 4
    t += gap; ev.append((t, CS, 1))
    return sorted(ev, key=lambda e: e[0]), samples, t + 200


def run(access, gap, core_lat_cycles, regs):
    header = [0x00, 0x39, 0x00]          # read VERSIONR
    ev, samples, tend = kos_read_frame(access, gap, header, 2)
    sm = SM(filler=0x00)
    level = {MOSI: 0, MISO: 1, SCLK: 0, CS: 1}
    hist = []                            # (cycle, levels) for 2-cycle sync
    pending = []                         # (due_cycle, byte) core1 pushes
    state = 0; addr = 0; misoline = []
    ei = 0; cyc = 0; got = []
    si = 0
    while cyc * CYCLE_NS < tend:
        tns = cyc * CYCLE_NS
        while ei < len(ev) and ev[ei][0] <= tns:
            level[ev[ei][1]] = ev[ei][2]; ei += 1
        hist.append(dict(level))
        synced = hist[-3] if len(hist) >= 3 else hist[0]
        # master samples MISO
        while si < len(samples) and samples[si] <= tns:
            misoline.append(sm.miso); si += 1
        # core1: react to RX bytes after latency
        while sm.rxf:
            b = sm.rxf.pop(0)
            if state == 0: addr = b << 8; state = 1
            elif state == 1: addr |= b; state = 2
            elif state == 2:
                state = 4
                pending.append((cyc + core_lat_cycles, regs[addr]))
                pending.append((cyc + core_lat_cycles + 3, regs[addr + 1]))
                addr += 2
            else:
                pending.append((cyc + 30, regs[addr])); addr += 1
        for p in list(pending):
            if p[0] <= cyc: sm.txf.append(p[1]); pending.remove(p)
        sm.step(synced)
        cyc += 1
    bytes_ = []
    for k in range(0, len(misoline) // 8):
        v = 0
        for bit in misoline[8 * k:8 * k + 8]: v = (v << 1) | bit
        bytes_.append(v)
    return bytes_


regs = [0] * 0x10000
regs[0x39] = 0x04; regs[0x3A] = 0xA5
print("access_ns gap_ns  max core1 latency (cycles @250MHz) that still returns 04 A5")
for access, gap in itertools.product([20, 40, 60], [60, 120, 250]):
    best = None
    for lat in range(0, 400, 2):
        if run(access, gap, lat, regs) == [0x04, 0xA5]: best = lat
        else: break
    print(f"  {access:5}   {gap:5}   {best}")
