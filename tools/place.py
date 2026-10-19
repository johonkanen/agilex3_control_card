"""First-pass component placement for the control card.

    squashfs-root/AppRun python3.11 -I tools/place.py hardware/control_card.kicad_pcb

Order:
1. Fixed parts (U1 BGA, J1, J2) and hand placements (MANUAL, incl. all buck cells; BUCK_CELLS row layout unused).
2. FPGA decoupling under the BGA: 0201s on supply/GND ball pairs, bulk in the via-free channels.
3. ICs, inductors and other multi-pin parts, packed into their group's region (inductors here, so the
   regulator caps placed later anchor to them).
4. The JTAG level shifter, on the bottom under the FPGA, in a via-free spot next to its SDM balls.
5. HyperRAM and flash decoupling on the other side, on their own VCC/VSS ball pairs (right after
   those two BGAs, before other parts can take the space).
6. Remaining 2-pin parts next to the pad they connect to (own side first, then the other side),
   falling back to the group's regions.

Only supply, ground and sense balls carry a via-in-pad; all signal I/O escapes on L1 and
unused balls (NC, DNU, spare I/O) have nothing, which leaves room under the FPGA and memories. Courtyards never overlap; through-hole pads block
both sides. Parts are grouped by the "Group" field written by tools/gen_schematic.py. This is a
starting point for hand placement, not a final layout.
"""
import math
import sys

import pcbnew

MM = pcbnew.FromMM
BOARD = (75.2, 94.9, 107.738, 128.7)
EDGE = 0.3          # keep courtyards this far inside the board edge
GAP = 0.05          # extra spacing between courtyards (courtyards already include assembly margin)
VIA_R = 0.175 + 0.1  # via-in-pad pad radius plus clearance, for keeping pads off foreign vias

FIXED = {"U1": (92.0, 113.0, 0, "top")}   # BGA where the ECP5 sat; J1/J2 already placed
BGA_SHADOW = (83.0, 104.0, 101.0, 122.0)   # bottom under the FPGA: only decoupling and the JTAG shifter

# group: (side, [regions x0, y0, x1, y1[, "up"]]); "up" fills from the bottom edge of the region,
# so the largest part (the ADC mux) lands next to J1's analog pins.
GROUPS = [
    # top strip, left to right: the two side-view RGB LEDs on the edge (MANUAL) with their resistors,
    # HyperRAM, flash pushed against it. The HyperRAM starts where LED D2's courtyard ends (x 84.0)
    ("leds", "top", [(75.5, 95.2, 84.0, 102.9)]),
    ("hyperram", "top", [(84.0, 95.2, 93.15, 102.9)]),
    ("flash", "top", [(93.15, 95.2, 103.0, 102.9)]),
    ("adc_a", "top", [(75.5, 102.9, 81.9, 124.9, "up"), (81.9, 123.1, 102.0, 124.9)]),
    ("osc", "bottom", [(84.0, 95.2, 103.3, 103.9), (75.5, 95.2, 84.0, 103.9)]),
    ("config", "bottom", [(84.0, 95.2, 103.3, 103.9), (75.5, 95.2, 84.0, 103.9)]),
    ("buck_core", "bottom", [(101.0, 109.8, 107.4, 125.1)]),
    ("ldo_1v8hr", "bottom", [(75.5, 95.2, 84.0, 103.9), (84.0, 95.2, 103.3, 103.9)]),
    ("ldo_1v2", "bottom", [(84.6, 122.0, 101.0, 125.1), (101.0, 109.8, 107.4, 125.1)]),
    ("input_5v", "bottom", [(84.6, 122.0, 101.0, 125.1), (101.0, 109.8, 107.4, 125.1)]),
    ("adc_b", "bottom", [(75.5, 103.9, 84.5, 125.1, "up"), (84.6, 122.0, 101.0, 125.1)]),
    ("ldo_analog", "bottom", [(75.5, 103.9, 84.5, 125.1), (84.6, 122.0, 101.0, 125.1)]),
    ("jtag", "bottom", [(83.0, 104.0, 101.0, 122.0)]),
    ("hyperram_decap", "bottom", [(75.5, 95.2, 103.3, 103.9)]),
    ("flash_decap", "bottom", [(75.5, 95.2, 103.3, 103.9)]),
]
SHADOW_OK = {"jtag"}   # groups allowed under the FPGA (with the via check)

# Hand placements to keep across rebuilds: (group, value, footprint name, side, x, y, rotation[, nets]).
# Parts are matched by group, value and footprint (not reference), in reference order; the optional
# nets tuple (net-name endings) picks out one of several identical parts.
MANUAL = [
    # side-view RGB LEDs on the north edge, lens out (2026-10-15): end-pad centres 1.8 mm from the edge as
    # on U25, D1's pads 0.3 mm from the west edge, D2 against D1's courtyard
    ("leds", "RGB", "LED_RGB_APFA3010_RightAngle", "top", 77.5, 96.7, 0),
    ("leds", "RGB", "LED_RGB_APFA3010_RightAngle", "top", 81.8, 96.7, 0),
    # 1.8 V buck cell, moved by hand partly under the FPGA's west edge (2026-10-12)
    ("buck_1v8", "AP61102Z6-7", "SOT-563", "bottom", 82.86, 105.45, 0),
    ("buck_1v8", "1u", "L_Cenker_CKCS201610", "bottom", 85.5, 106.0, 90),
    ("buck_1v8", "10u", "C_0603_1608Metric", "bottom", 83.14, 108.37, 0),
    ("buck_1v8", "22u", "C_0603_1608Metric", "bottom", 83.14, 109.97, 0),
    ("buck_1v8", "22p", "C_0402_1005Metric", "bottom", 85.67, 109.6, 0),   # 0.1 mm up: clears GND ball T4
    ("buck_1v8", "200k", "R_0402_1005Metric", "bottom", 85.69, 108.11, 0),
    ("buck_1v8", "100k", "R_0402_1005Metric", "bottom", 82.59, 107.01, 0),
    ("buck_1v8", "100k", "R_0402_1005Metric", "bottom", 82.59, 111.31, 0),
    # East buck cells (2026-10-16), both laid out "-|" toward the FPGA: the inductor lies east-west with its
    # output pad west, the first output cap stands north-south just west of it, and the regulator sits under
    # the inductor's east (SW) end with its input cap beside it, away from the FPGA. The output plane then
    # feeds in from the FPGA side and never runs under the switcher (L4 +0V75 island stops at x 102.3).
    # 3.3 V cell (top), under J2's courtyard: U4 at 90 degrees puts SW at its north-east corner under L3's
    # SW pad and FB at its south-west corner; C8 (input) lies under the VIN/GND pins, C7 + R9 (+3V3/FB)
    # stand side by side with R10 below, so the FB node is three adjacent pads next to the FB pin.
    ("buck_3v3", "22u", "C_0603_1608Metric", "top", 102.875, 111.425, 90),
    ("buck_3v3", "1u", "L_Cenker_CKCS201610", "top", 105.245, 111.245, 180),
    ("buck_3v3", "AP61102Z6-7", "SOT-563", "top", 105.445, 113.885, 90),
    ("buck_3v3", "10u", "C_0603_1608Metric", "top", 105.865, 115.955, 180),
    ("buck_3v3", "200k", "R_0402_1005Metric", "top", 103.695, 114.065, 90),
    ("buck_3v3", "44k2", "R_0402_1005Metric", "top", 102.615, 116.155, 90),
    ("buck_3v3", "22p", "C_0402_1005Metric", "top", 102.615, 114.065, 90),
    # core cell (bottom): output caps C2/C3 in the column against the BGA keep-out, over the +0V75
    # island; U2 at 0 degrees has VIN top-left and SW top-right, so C1 (input) stands west of it and L1
    # lies above. The divider sits under U2 with sense pads west (the L6 sense pair arrives from the west
    # below C1), R3/R4 hang under them (HANG); the PG pull-up R5 and the 100n input cap C16 stand on
    # the east edge next to the PG/EN pins, over the L3 +5V strip
    ("buck_core", "22u", "C_0603_1608Metric", "bottom", 101.835, 110.525, 90),
    ("buck_core", "22u", "C_0603_1608Metric", "bottom", 101.835, 113.625, 90),
    ("buck_core", "1u", "L_Cenker_CKCS201610", "bottom", 105.195, 110.345, 180),
    ("buck_core", "AP61302Z6-7", "SOT-563", "bottom", 105.495, 112.735, 0),
    ("buck_core", "10u", "C_0603_1608Metric", "bottom", 103.435, 113.265, 90),
    ("buck_core", "49k9", "R_0402_1005Metric", "bottom", 105.275, 115.375, 0),
    ("buck_core", "200k", "R_0402_1005Metric", "bottom", 105.275, 118.465, 0),
    ("buck_core", "100k", "R_0402_1005Metric", "bottom", 106.925, 114.755, 90),
    ("input_5v", "100n", "C_0402_1005Metric", "bottom", 106.925, 116.755, 90),
    ("input_5v", "22u", "C_0805_2012Metric", "bottom", 99.369, 124.504, 0),   # 5 V bulk by J1
    # 1.2 V LDO under the divider, turned so its output pin and C11 face west; input cap C10 above the
    # +3V3 pins at the east edge, leaving a lane between the divider and the LDO for the PG link
    ("ldo_1v2", "TLV75512PDBVR", "SOT-23-5", "bottom", 105.3, 123.3, 180),
    # bank 6C / HyperRAM 1.8 V LDO in the north-west strip, output pin toward the +1V8_HR island on L3 (x >= 85.2),
    # GND pin with room for its via (the corner spot left it no via clear of the board edge)
    ("ldo_1v8hr", "TLV75518PDBVR", "SOT-23-5", "bottom", 81.8, 96.95, 0),
    ("ldo_1v2", "4u7", "C_0603_1608Metric", "bottom", 102.375, 123.085, 90),
    ("ldo_1v2", "1u", "C_0402_1005Metric", "bottom", 106.415, 120.995, 0),
    # ADC front ends (2026-10-17), per the ADS7056 layout guidelines: kickback RC at AINP and the AVDD (reference) caps at
    # the AVDD pin on the ADC's own side, no via between. Chain mux -> buffer -> RC -> ADC kept compact, digital side north.
    # ADC A (top): ADC above its buffer; its series resistors are left to the packer, next to the digital pins
    ("adc_a", "SN74LV4051APWR", "TSSOP-16_4.4x5mm_P0.65mm", "top", 78.30, 121.00, -90),
    ("adc_a", "OPA365AIDBVR", "SOT-23-5", "top", 77.59, 115.16, 180),
    ("adc_a", "ADS7056IRUGR", "Texas_UQFN-8_1.5x1.5mm_P0.5mm", "top", 78.0, 109.0, -90),
    ("adc_a", "1u", "C_0402_1005Metric", "top", 76.015, 109.0, 90, ("+3V3",)),        # DVDD, west pin
    ("adc_a", "4u7", "C_0603_1608Metric", "top", 77.22, 111.25, 180),                 # AVDD reference cap under the AVDD pin
    ("adc_a", "100n", "C_0402_1005Metric", "top", 76.645, 112.595, 180),
    ("adc_a", "680p", "C_0402_1005Metric", "top", 79.315, 111.425, 270),             # kickback C at AINP
    ("adc_a", "33R", "R_0402_1005Metric", "top", 80.395, 111.425, 90, ("AINP_A",)),  # kickback R
    # ADC B (bottom): ADC moved from the J1 edge to just east of its buffer, RC and AVDD caps below it
    ("adc_b", "SN74LV4051APWR", "TSSOP-16_4.4x5mm_P0.65mm", "bottom", 78.30, 121.20, -90),
    ("adc_b", "OPA365AIDBVR", "SOT-23-5", "bottom", 77.59, 115.36, 180),
    ("adc_b", "ADS7056IRUGR", "Texas_UQFN-8_1.5x1.5mm_P0.5mm", "bottom", 81.40, 113.40, -90),
    ("adc_b", "33R", "R_0402_1005Metric", "bottom", 78.955, 113.045, 0, ("AINP_B",)),  # kickback R over the buffer output
    ("adc_b", "680p", "C_0402_1005Metric", "bottom", 80.255, 115.81, 270),          # kickback C under AINP
    ("adc_b", "4u7", "C_0603_1608Metric", "bottom", 81.915, 116.355, 270),          # AVDD reference cap under AVDD
    ("adc_b", "100n", "C_0402_1005Metric", "bottom", 83.255, 115.81, 270),
    # SDM strap/config resistors, moved by hand next to the SDM balls they serve (2026-10-12)
    # JTAG level shifter, moved north under the FPGA's north edge to free the SDM corner (2026-10-12)
    ("jtag", "SN74AVC4T774RSVR", "UQFN-16_1.8x2.6mm_P0.4mm", "bottom", 98.1, 103.6, 0),
    ("config", "4k7", "R_0402_1005Metric", "top", 104.0, 123.5, 0, ("MSEL2", "GND")),
    ("config", "4k7", "R_0402_1005Metric", "top", 104.0, 122.5, 180, ("MSEL2", "+1V8")),
    ("config", "4k7", "R_0402_1005Metric", "top", 105.55, 123.0, 90, ("MSEL1",)),   # beside the MSEL2 pair
    ("config", "10k", "R_0402_1005Metric", "top", 103.5, 119.5, 180, ("NCONFIG",)),
    ("config", "10k", "R_0402_1005Metric", "top", 103.5, 120.5, 180, ("NSTATUS",)),
    ("config", "2k", "R_0402_1005Metric", "top", 103.5, 118.5, 180, ("RREF_SDM",)),
]

# Buck cells laid out in rows (too tight for the packer): (group, side, x0, y0, rows).
# A row lists part roles: U = regulator, L = inductor, CIN = 10u, COUT = 22u, FB = feedback divider and
# feed-forward cap, PG = power-good pull-up, SNSP/SNSG = core sense fallbacks, S = any other small part;
# a trailing 90 rotates the part; "_<mm>" leaves an empty slot that wide.
# All three buck cells are hand placed now (MANUAL); the row layout is kept for trying new cells.
BUCK_CELLS = []

# Parts hung under another part's sense pad after orientation: (group, role, anchor role). The core
# sense fallbacks stand vertically under the divider's sense pads (SNSP in the gap between the
# divider rows), so each joins its lane with a short stub and its other pad goes to the plane by via
HANG = [("buck_core", "SNSP", "FBP"), ("buck_core", "SNSG", "FBN")]
SENSE_NETS = ("VCC_SENSE_P", "VCC_SENSE_N")
BUCKS_PG = ("buck_core",)   # cells whose PG pull-up sits in a row slot under the regulator

# Memory BGAs whose decoupling sits on their own VCC/VSS ball pairs (1.0 mm apart, 0402 pads
# at +-0.48 mm): (decap group, group of the BGA part, ball-pair distance range)
MEM_DECAPS = [("hyperram_decap", "hyperram", (0.95, 1.05)), ("flash_decap", "flash", (0.95, 1.05))]


# ------------------------------------------------------------------ geometry helpers

def npads(fp):
    """Copper pads with a number (0201 footprints add two unnumbered paste-only pads)."""
    return sum(1 for p in fp.Pads() if p.GetNumber())


def side_of(fp):
    return "bottom" if fp.IsFlipped() else "top"


def crtyd(side):
    return pcbnew.B_CrtYd if side == "bottom" else pcbnew.F_CrtYd


def bbox_mm(fp, side_layer):
    bb = fp.GetCourtyard(side_layer).BBox()
    if bb.GetWidth() == 0:
        bb = fp.GetBoundingBox(False)
    return (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))


def overlaps(a, b, gap=None):
    g = GAP if gap is None else gap
    e = 1e-6
    return not (a[2] + g <= b[0] + e or b[2] + g <= a[0] + e or a[3] + g <= b[1] + e or b[3] + g <= a[1] + e)


def pad_mm(pad):
    c = pad.GetPosition()
    return pcbnew.ToMM(c.x), pcbnew.ToMM(c.y)


def set_side(fp, side):
    if (side == "bottom") != fp.IsFlipped():
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)


def place_at(fp, x, y, rot):
    fp.SetOrientationDegrees(rot)
    fp.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))


class Packer:
    def __init__(self):
        self.taken = {"top": [], "bottom": []}
        self.allow_shadow = False

    def block(self, side, box):
        self.taken[side].append(box)

    def free(self, side, box, gap=None):
        x0, y0, x1, y1 = BOARD
        if box[0] < x0 + EDGE or box[1] < y0 + EDGE or box[2] > x1 - EDGE or box[3] > y1 - EDGE:
            return False
        if side == "bottom" and not self.allow_shadow and overlaps(box, BGA_SHADOW):
            return False
        return not any(overlaps(box, t, gap) for t in self.taken[side])


VIA_NETS = ("GND", "VCC_SENSE_P", "VCC_SENSE_N")   # plus every "+" rail


def needs_via(net):
    """Only supply, ground and sense balls get a via-in-pad: all signal I/O escapes on L1."""
    return net in VIA_NETS or net.startswith("+")


def ball_vias(fp):
    """(net, x, y) of every BGA ball that carries a via-in-pad."""
    return [(p.GetNetname(), *pad_mm(p)) for p in fp.Pads() if needs_via(p.GetNetname())]


def pads_clear(fp, vias, own=None):
    """True if no copper pad of fp comes near a via of another net. own: {pad number: allowed net}."""
    own = own or {}
    for pad in fp.Pads():
        if not pad.GetNumber():
            continue
        bb = pad.GetBoundingBox()
        x0, y0, x1, y1 = (pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
        for net, bx, by in vias:
            if net and net == own.get(pad.GetNumber()):
                continue
            if x0 - VIA_R < bx < x1 + VIA_R and y0 - VIA_R < by < y1 + VIA_R:
                return False
    return True


# ------------------------------------------------------------------ placement strategies

def try_regions(fp, side, regions, pk, check=None):
    layer = crtyd(side)
    bx = bbox_mm(fp, layer)
    if (bx[2] - bx[0]) * (bx[3] - bx[1]) < 2.5 and len(regions) > 1:
        regions = regions[1:] + regions[:1]   # small parts fill the overflow region first
    for rot in (0, 90):
        place_at(fp, 0, 0, rot)
        bx = bbox_mm(fp, layer)
        w, h = bx[2] - bx[0], bx[3] - bx[1]
        for r in regions:
            up = len(r) > 4 and r[4] == "up"
            n = int((r[3] - r[1] - h) / 0.25 + 1e-6) + 1
            ys = [r[3] - h - k * 0.25 for k in range(n)] if up else [r[1] + k * 0.25 for k in range(n)]
            for y in ys:
                x = r[0]
                while x + w <= r[2] + 1e-6:
                    box = (x, y, x + w, y + h)
                    if pk.free(side, box):
                        place_at(fp, x - bx[0], y - bx[1], rot)
                        if check is None or check(fp):
                            pk.block(side, box)
                            return True
                    x += 0.25
    return False


def place_near(fp, side, target, pk, max_r=10.0, step=0.25, check=None, gap=None):
    """Nearest free spot to target (courtyard centre), rotations 0/90; check(fp) can veto."""
    set_side(fp, side)
    layer = crtyd(side)
    shapes = []
    for rot in (0, 90):
        place_at(fp, 0, 0, rot)
        shapes.append((rot, bbox_mm(fp, layer)))
    for ring in range(int(max_r / step) + 1):
        cands = []
        for i in range(-ring, ring + 1):
            for j in (-ring, ring) if abs(i) != ring else range(-ring, ring + 1):
                dx, dy = i * step, j * step
                for rot, bx in shapes:
                    w, h = bx[2] - bx[0], bx[3] - bx[1]
                    cx, cy = target[0] + dx, target[1] + dy
                    cands.append((dx * dx + dy * dy, rot, bx, (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)))
        for _, rot, bx, box in sorted(cands, key=lambda c: c[0]):
            if pk.free(side, box, gap):
                place_at(fp, box[0] - bx[0], box[1] - bx[1], rot)
                if check is None or check(fp):
                    pk.block(side, box)
                    return True
    return False


def role_of(fp):
    v, fpid = fp.GetValue(), fp.GetFPIDAsString()
    if fpid.endswith("SOT-563"):
        return "U"
    nets = {p.GetNetname() for p in fp.Pads()}
    if any(n.startswith("/Power/FB_") for n in nets):
        return "FB"   # feedback divider resistors and the feed-forward cap
    if any(n.startswith("/Power/PG_") for n in nets):
        return "PG"   # power-good pull-up
    if "VCC_SENSE_P" in nets:
        return "SNSP"   # core sense fallback, +0V75 side
    if "VCC_SENSE_N" in nets:
        return "SNSG"   # core sense fallback, GND side
    if "Inductor" in fpid:
        return "L"
    if v == "10u":
        return "CIN"
    if v == "22u":
        return "COUT"
    return "S"


def role_ok(fp, want):
    """FBP / FBN: a feedback divider part that is also on VCC_SENSE_P / VCC_SENSE_N."""
    if want in ("FBP", "FBN"):
        nets = {p.GetNetname() for p in fp.Pads()}
        return role_of(fp) == "FB" and ("VCC_SENSE_P" if want == "FBP" else "VCC_SENSE_N") in nets
    return role_of(fp) == want


def place_cell(fps, group, side, x0, y0, rows, pk):
    parts = [fp for fp in fps.values() if fp.GetFieldText("Group") == group]
    layer = crtyd(side)
    y = y0
    placed = []
    u_box = None
    for row in rows:
        x = x0
        row_items = []   # (fp, box): placed but not yet blocked, so the row can still be adjusted
        for want in row:
            if want.startswith("_"):   # empty slot: the PG link runs down here from the pull-up
                x += float(want[1:]) + GAP
                continue
            rot = 90 if want.endswith("90") else 0
            role = want.rstrip("90")
            fp = next((p for p in parts if p not in placed and role_ok(p, role)), None)
            if fp is None:
                continue
            set_side(fp, side)
            place_at(fp, 0, 0, rot)
            bx = bbox_mm(fp, layer)
            place_at(fp, x - bx[0], y - bx[1], rot)
            box = (x, y, x + bx[2] - bx[0], y + bx[3] - bx[1])
            row_items.append((fp, box))
            placed.append(fp)
            x = box[2] + GAP
        roles = {role_of(f): (f, b) for f, b in row_items}   # FBP/FBN parts count as FB here
        if "U" in roles and "L" in roles:
            # switch-node alignment: inductor pad 1 (SW) is the upper pad and lines up with the IC's
            # SW pin (4), so the SW track is short and straight and pad 2 (output) faces the caps below
            (u, ub), (ind, lb) = roles["U"], roles["L"]
            pad = lambda f, n: next(p for p in f.Pads() if p.GetNumber() == n)   # noqa: E731
            if pad_mm(pad(ind, "1"))[1] > pad_mm(pad(ind, "2"))[1]:
                c = ((lb[0] + lb[2]) / 2, (lb[1] + lb[3]) / 2)
                ind.SetOrientationDegrees(ind.GetOrientationDegrees() + 180)
                b2 = bbox_mm(ind, layer)
                ind.SetPosition(ind.GetPosition() + pcbnew.VECTOR2I(MM(c[0] - (b2[0] + b2[2]) / 2), MM(c[1] - (b2[1] + b2[3]) / 2)))
            dy = pad_mm(pad(u, "4"))[1] - pad_mm(pad(ind, "1"))[1]
            mover = ind if dy > 0 else u
            mover.SetPosition(mover.GetPosition() + pcbnew.VECTOR2I(0, MM(abs(dy))))
            row_items = [(f, bbox_mm(f, layer)) for f, _ in row_items]
        row_h = max([b[3] for _, b in row_items] + [y]) - y
        for f, box in row_items:
            if not pk.free(side, box):
                print(f"warning: {f.GetReference()} in {group} overlaps or leaves the board")
            pk.block(side, box)
            if role_of(f) == "U":
                u_box = box
        if row_items and "U" in roles and u_box:   # one small part fits under the regulator, beside the taller inductor
            fp = next((p for p in parts if p not in placed and role_of(p) == "S"), None)
            if fp is not None:
                set_side(fp, side)
                place_at(fp, 0, 0, 0)
                bx = bbox_mm(fp, layer)
                box = (u_box[0], u_box[3] + GAP, u_box[0] + bx[2] - bx[0], u_box[3] + GAP + bx[3] - bx[1])
                if box[3] <= y + row_h + GAP + 1e-6 and pk.free(side, box):
                    place_at(fp, box[0] - bx[0], box[1] - bx[1], 0)
                    pk.block(side, box)
                    placed.append(fp)
        y += row_h + GAP
    rest = [p.GetReference() for p in parts if p not in placed]
    return [p.GetReference() for p in placed], rest


def place_on_ball_pairs(caps, bga, side, dist, pk):
    """Put each cap with its rail pad on a rail ball and its GND pad on the neighbouring GND ball
    (pads on the via-in-pads), spreading caps over the rail's balls. Returns the caps left over."""
    vias = ball_vias(bga)
    gnd = [(x, y) for n, x, y in vias if n == "GND"]
    used, placed, left = set(), [], []
    for fp in caps:
        set_side(fp, side)
        cu = [p for p in fp.Pads() if p.GetNumber()]          # skip paste-only pads
        rail = next(p.GetNetname() for p in cu if p.GetNetname() != "GND")
        rail_pad = next(p.GetNumber() for p in cu if p.GetNetname() == rail)
        own = {p.GetNumber(): p.GetNetname() for p in cu}
        pairs = [((rx, ry), (gx, gy)) for n, rx, ry in vias if n == rail and (rx, ry) not in used
                 for gx, gy in gnd
                 if dist[0] <= math.hypot(gx - rx, gy - ry) <= dist[1] and (abs(gx - rx) < 0.05 or abs(gy - ry) < 0.05)]
        same = [q for r, q in placed if r == rail]
        pairs.sort(key=lambda pr: -min([math.hypot(pr[0][0] - a, pr[0][1] - b) for a, b in same] or [99]))
        ok = False
        for (rx, ry), (gx, gy) in pairs:
            for rot in (0, 90, 180, 270):
                place_at(fp, (rx + gx) / 2, (ry + gy) / 2, rot)
                p_r = next(p for p in fp.Pads() if p.GetNumber() == rail_pad)
                if math.hypot(pad_mm(p_r)[0] - rx, pad_mm(p_r)[1] - ry) < 0.1:
                    break
            bx = bbox_mm(fp, crtyd(side))
            if pk.free(side, bx, gap=0.0) and pads_clear(fp, vias, own):
                pk.block(side, bx)
                used.add((rx, ry))
                placed.append((rail, (rx, ry)))
                ok = True
                break
        if not ok:
            left.append(fp)
    return left


def place_fpga_decaps(fps, pk):
    """0201s on supply/GND ball pairs; bulk caps in the via-free channels under the BGA."""
    u1 = fps["U1"]
    vias = ball_vias(u1)
    caps = [fp for fp in fps.values() if fp.GetFieldText("Group").startswith("decap")]
    pk.allow_shadow = True
    # bead-filtered supplies (one or two balls each) first, then the rails with the fewest ball pairs
    order = ["+1V2", "+3V3", "+1V8", "+0V75"]

    def rail_of(f):
        """The cap's supply net; for a filter bead, the filtered side (its parts belong next to that ball)."""
        nets = [p.GetNetname() for p in f.Pads() if p.GetNumber() and p.GetNetname() != "GND"]
        return next((n for n in nets if n not in order), nets[0])
    small = sorted([c for c in caps if "0201" in c.GetFPIDAsString()],
                   key=lambda f: (order.index(rail_of(f)) if rail_of(f) in order else -1, f.GetReference()))
    left = place_on_ball_pairs(small, u1, "bottom", (0.7, 0.8), pk)
    for fp in sorted([c for c in caps if "0201" not in c.GetFPIDAsString()], key=lambda f: rail_of(f) in order):
        set_side(fp, "bottom")
        rail = rail_of(fp)
        pts = [(x, y) for n, x, y in vias if n == rail]
        target = (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
        if not place_near(fp, "bottom", target, pk, max_r=9.0, check=lambda f: pads_clear(f, vias)
                          and overlaps(bbox_mm(f, pcbnew.B_CrtYd), BGA_SHADOW, 0.0)):
            left.append(fp)
    pk.allow_shadow = False
    for fp in left:   # nearest free spot outside the via field
        rail = rail_of(fp)
        pts = [(x, y) for n, x, y in vias if n == rail]
        target = (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
        if place_near(fp, "bottom", target, pk, max_r=16.0):
            print(f"note: {fp.GetReference()} ({fp.GetValue()}) placed outside the BGA area")
        else:
            print(f"warning: {fp.GetReference()} could not be placed")
    return [fp.GetReference() for fp in caps]


def place_jtag_shifter(fps, pk, group_of, done):
    """Level shifter on the bottom under the FPGA, next to the SDM JTAG balls, clear of all vias."""
    u1 = fps["U1"]
    vias = ball_vias(u1)
    ic = next(f for f in fps.values() if group_of(f) == "jtag" and npads(f) > 2)
    if ic.GetReference() in done:   # hand-placed (MANUAL)
        return []
    pts = [pad_mm(p) for p in u1.Pads() if p.GetNetname().endswith(("TCK_1V8", "TDI_1V8", "TMS_1V8", "TDO_1V8"))]
    target = (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
    pk.allow_shadow = True
    ok = place_near(ic, "bottom", target, pk, max_r=12.0, check=lambda f: pads_clear(f, vias))
    pk.allow_shadow = False
    if not ok:
        print(f"warning: no via-free spot under the FPGA for {ic.GetReference()}")
    return [ic.GetReference()] if ok else []


def place_mem_decaps(fps, pk, group_of):
    done = []
    for dgroup, pgroup, dist in MEM_DECAPS:
        bga = next(f for f in fps.values() if group_of(f) == pgroup and npads(f) > 20)
        side = "bottom" if side_of(bga) == "top" else "top"
        caps = sorted([f for f in fps.values() if group_of(f) == dgroup], key=lambda f: f.GetValue() != "100n")
        vias = ball_vias(bga)
        left = place_on_ball_pairs(caps, bga, side, dist, pk)
        bb = bga.GetBoundingBox(False)
        centre = (pcbnew.ToMM(bb.GetCenter().x), pcbnew.ToMM(bb.GetCenter().y))
        for fp in left:
            if not place_near(fp, side, centre, pk, max_r=8.0, check=lambda f: pads_clear(f, vias)):
                print(f"warning: {fp.GetReference()} could not be placed near {bga.GetReference()}")
        done += [f.GetReference() for f in caps]
    return done


# (group, footprint match, pad that should face its net partner): flip such parts 180 degrees
# (same courtyard) when that brings the pad closer to the other pad on its net.
ORIENT = [("adc_a", "TSSOP-16", "3"), ("adc_b", "TSSOP-16", "3"),   # mux COM output toward the buffer
          ("adc_a", "SOT-23-5", "3"), ("adc_b", "SOT-23-5", "3")]   # buffer + input toward the mux
# buck cells: inductor SW pad toward the IC's SW pin; input cap's supply pad toward the IC's VIN pin;
# output cap's supply pad toward the inductor's output pad
for _g in ("buck_core", "buck_1v8", "buck_3v3"):
    ORIENT += [(_g, "C_0603", "CAP")]   # input cap toward VIN (U pin 3), output cap toward the inductor output
ORIENT += [("buck_1v8", "Inductor", "1")]   # hand-placed cell; the row cells align their inductor in place_cell
# FB divider/feed-forward parts: FB pad toward the regulator's FB pin (pin 1); in the core cell the
# divider's sense pad faces the FPGA's sense ball instead (west, where the L6 sense pair comes from)
for _g in ("buck_1v8", "buck_3v3"):
    ORIENT += [(_g, "_0402_", "FB>U1")]
ORIENT += [("buck_core", "_0402_", "SENSE>U1")]
# power-good pull-up: PG pad toward the regulator's PG pin (straight under it), the supply pad away
for _g in BUCKS_PG:
    ORIENT += [(_g, "_0402_", "PG>U")]


# (group, footprint match, pad): turn the part in place (square body) so that pad faces north. The ADCs'
# digital side (CS/SDO/SCLK, pad 2 in the middle) points north, toward the FPGA's I/O.
FACE_NORTH = [("adc_a", "UQFN-8", "2"), ("adc_b", "UQFN-8", "2")]


def face_north(fps, group_of):
    for group, fpname, padnum in FACE_NORTH:
        for fp in fps.values():
            if group_of(fp) != group or fpname not in fp.GetFPIDAsString():
                continue
            c = fp.GetPosition()
            best = None
            for rot in (0, 90, 180, 270):
                fp.SetOrientationDegrees(rot)
                fp.SetPosition(c)
                y = pad_mm(next(q for q in fp.Pads() if q.GetNumber() == padnum))[1]
                if best is None or y < best[0] - 1e-6:
                    best = (y, rot)
            fp.SetOrientationDegrees(best[1])
            fp.SetPosition(c)


def hang_parts(fps, group_of, pk):
    """HANG: stand each part vertically under its anchor's sense pad, the pad on the anchor's
    net on top. Returns the parts that did not fit."""
    failed = []
    for group, role, anchor_role in HANG:
        part = next((f for f in fps.values() if group_of(f) == group and role_of(f) == role), None)
        anchor = next((f for f in fps.values() if group_of(f) == group and role_ok(f, anchor_role)), None)
        if part is None or anchor is None:
            continue
        side = side_of(anchor)
        layer = crtyd(side)
        set_side(part, side)
        a_pad = next(p for p in anchor.Pads() if p.GetNetname() in SENSE_NETS)
        ax, _ = pad_mm(a_pad)
        top = bbox_mm(anchor, layer)[3] + GAP + 0.01   # the packer's free check is strict at GAP
        best = None
        for rot in (90, 270):
            place_at(part, 0, 0, rot)
            b = bbox_mm(part, layer)
            place_at(part, ax - (b[0] + b[2]) / 2, top - b[1], rot)
            p = next(q for q in part.Pads() if q.GetNetname() == a_pad.GetNetname())
            d = pad_mm(p)[1]
            if best is None or d < best[0]:
                best = (d, rot)
        place_at(part, 0, 0, best[1])
        b = bbox_mm(part, layer)
        place_at(part, ax - (b[0] + b[2]) / 2, top - b[1], best[1])
        box = bbox_mm(part, layer)
        if not pk.free(side, box):
            print(f"warning: {part.GetReference()} hung under {anchor.GetReference()} overlaps")
            failed.append(f"{part.GetReference()}({group})")
        pk.block(side, box)
    return failed


def orient_parts(fps, group_of):
    for group, fpname, padnum in ORIENT:
        for fp in fps.values():
            if group_of(fp) != group or fpname not in fp.GetFPIDAsString():
                continue
            pnum = padnum
            if padnum == "CAP":   # supply pad (1) of an input/output cap, aimed at the pin it serves
                cin = role_of(fp) == "CIN"
                pnum = "1"
                pad = next(p for p in fp.Pads() if p.GetNumber() == "1")
                net = pad.GetNetname()
                partner = [pad_mm(op) for f in fps.values() if group_of(f) == group and role_of(f) == ("U" if cin else "L")
                           for op in f.Pads() if op.GetNumber() == ("3" if cin else "2")]
            elif padnum == "PG>U":   # the pull-up's pad on a /Power/PG_ net, aimed at the regulator's pin on it
                if role_of(fp) != "PG":
                    continue
                pad = next((p for p in fp.Pads() if p.GetNetname().startswith("/Power/PG_")), None)
                if pad is None:
                    continue
                pnum = pad.GetNumber()
                net = pad.GetNetname()
                partner = [pad_mm(op) for f in fps.values() if group_of(f) == group and role_of(f) == "U"
                           for op in f.Pads() if op.GetNetname() == net]
            elif padnum == "SENSE>U1":   # a divider's sense pad, aimed at the FPGA's ball on that net
                if role_of(fp) != "FB":
                    continue
                pad = next((p for p in fp.Pads() if p.GetNetname() in SENSE_NETS), None)
                if pad is None:
                    continue
                pnum = pad.GetNumber()
                net = pad.GetNetname()
                partner = [pad_mm(op) for op in fps["U1"].Pads() if op.GetNetname() == net]
            elif padnum == "FB>U1":   # the pad on the FB net, aimed at the regulator's pin 1
                pad = next((p for p in fp.Pads() if p.GetNetname().startswith("/Power/FB_")), None)
                if pad is None:
                    continue
                pnum = pad.GetNumber()
                net = pad.GetNetname()
                partner = [pad_mm(op) for f in fps.values() if group_of(f) == group and role_of(f) == "U"
                           for op in f.Pads() if op.GetNumber() == "1"]
            else:
                pad = next(p for p in fp.Pads() if p.GetNumber() == pnum)
                net = pad.GetNetname()
                partner = [pad_mm(op) for f in fps.values()   # partners within the same group only
                           if f.GetReference() != fp.GetReference() and group_of(f) == group
                           for op in f.Pads() if op.GetNetname() == net]
            if not partner:
                continue
            layer = crtyd(side_of(fp))

            def recentre(target):
                b = bbox_mm(fp, layer)
                c = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
                fp.SetPosition(fp.GetPosition() + pcbnew.VECTOR2I(MM(target[0] - c[0]), MM(target[1] - c[1])))
            b0 = bbox_mm(fp, layer)
            centre = ((b0[0] + b0[2]) / 2, (b0[1] + b0[3]) / 2)
            rot0 = fp.GetOrientationDegrees()
            others = [op.GetBoundingBox() for f in fps.values() if group_of(f) == group and f.GetReference() != fp.GetReference()
                      for op in f.Pads() if op.GetNumber() and op.GetNetname() != net]
            others = [tuple(pcbnew.ToMM(v) for v in (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom())) for b in others]
            best = None
            for rot in (rot0, (rot0 + 180) % 360):   # rotate about the courtyard centre
                fp.SetOrientationDegrees(rot)
                recentre(centre)
                p = next(q for q in fp.Pads() if q.GetNumber() == pnum)
                px, py = pad_mm(p)
                tx, ty = min(partner, key=lambda c: math.hypot(px - c[0], py - c[1]))
                d = math.hypot(px - tx, py - ty)
                # penalise a straight 0.35 mm run that would come within clearance of another net's pad
                # in the group (e.g. the regulator's PG pin next to its SW pin)
                for k in range(41):
                    sx, sy = px + (tx - px) * k / 40, py + (ty - py) * k / 40
                    if any(math.hypot(max(b[0] - sx, 0, sx - b[2]), max(b[1] - sy, 0, sy - b[3])) < 0.175 + 0.15
                           for b in others):
                        d += 5.0
                        break
                if best is None or d < best[0]:
                    best = (d, rot)
            fp.SetOrientationDegrees(best[1])
            recentre(centre)


def find_anchor(fp, placed, group_of):
    """Pad of an already placed part that shares a net with fp: signal nets first, then rails;
    same group first. The FPGA is never an anchor. Returns (x, y) or None."""
    best = None
    for pad in fp.Pads():
        net = pad.GetNetname()
        if not net or net == "GND" or net.startswith("unconnected"):
            continue
        rail = net.startswith("+")
        for other in placed:
            if other.GetReference() == "U1" or other.GetReference() == fp.GetReference():
                continue
            for op in other.Pads():
                if op.GetNetname() == net:
                    key = (rail, group_of(other) != group_of(fp))
                    if best is None or key < best[0]:
                        best = (key, pad_mm(op))
    return best[1] if best else None


# ------------------------------------------------------------------ main

def main(path):
    board = pcbnew.LoadBoard(path)
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    group_of = lambda f: f.GetFieldText("Group")   # noqa: E731
    pk = Packer()
    for ref, (x, y, rot, side) in FIXED.items():
        set_side(fps[ref], side)
        place_at(fps[ref], x, y, rot)
    for ref in list(FIXED) + ["J1", "J2"]:
        fp = fps[ref]
        side = side_of(fp)
        pk.block(side, bbox_mm(fp, crtyd(side)))
        for pad in fp.Pads():   # through-hole pads block the other side too
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                b = pad.GetBoundingBox()
                c = 0.1   # copper clearance
                pk.block("bottom" if side == "top" else "top",
                         (pcbnew.ToMM(b.GetLeft()) - c, pcbnew.ToMM(b.GetTop()) - c,
                          pcbnew.ToMM(b.GetRight()) + c, pcbnew.ToMM(b.GetBottom()) + c))
    done = set(FIXED) | {"J1", "J2"}
    failed = []
    vias_all = ball_vias(fps["U1"])
    for group, value, fpname, side, x, y, rot, *rest in MANUAL:
        want = rest[0] if rest else ()

        def has_nets(f):
            nets = {p.GetNetname() for p in f.Pads() if p.GetNumber()}
            return all(any(n.endswith(w) for n in nets) for w in want)
        fp = next((f for r, f in sorted(fps.items()) if r not in done and group_of(f) == group
                   and f.GetValue() == value and str(f.GetFPID().GetLibItemName()) == fpname
                   and has_nets(f)), None)
        if fp is None:
            print(f"warning: no part for manual placement {group} {value} {fpname}")
            continue
        set_side(fp, side)
        place_at(fp, x, y, rot)
        pk.block(side, bbox_mm(fp, crtyd(side)))
        done.add(fp.GetReference())
        if side == "bottom":
            for pad in fp.Pads():
                if not pad.GetNumber():
                    continue
                bb = pad.GetBoundingBox()
                x0_, y0_, x1_, y1_ = (pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
                for net, bx, by in vias_all:
                    if net != pad.GetNetname() and x0_ - VIA_R < bx < x1_ + VIA_R and y0_ - VIA_R < by < y1_ + VIA_R:
                        ball = next(q.GetNumber() for q in fps["U1"].Pads() if pad_mm(q) == (bx, by))
                        print(f"via conflict: {fp.GetReference()} pad {pad.GetNumber()} [{pad.GetNetname()}] "
                              f"over FPGA ball {ball} [{net}]")
    for group, side, x0, y0, rows in BUCK_CELLS:
        placed, rest = place_cell(fps, group, side, x0, y0, rows, pk)
        done.update(placed)
        hung = {r for r in rest if any(g == group and role_of(fps[r]) == role for g, role, _ in HANG)}
        failed += [f"{r}({group})" for r in rest if r not in hung]
        done.update(rest)
    done.update(place_fpga_decaps(fps, pk))
    side_for = {name: side for name, side, _ in GROUPS}
    regions_for = {name: regions for name, _, regions in GROUPS}
    vias_u1 = ball_vias(fps["U1"])

    def check_for(name):
        return (lambda f: pads_clear(f, vias_u1)) if name in SHADOW_OK else None

    # multi-pin parts and inductors by region (the JTAG shifter has its own rule); inductors go
    # first so a regulator's caps can anchor to them
    done.update(place_jtag_shifter(fps, pk, group_of, done))
    big = lambda f: npads(f) > 2 or "Inductor" in f.GetFPIDAsString()   # noqa: E731
    for name, side, regions in GROUPS:
        refs = [r for r, f in fps.items() if r not in done and group_of(f) == name and big(f)]
        for r in refs:
            set_side(fps[r], side)
        refs.sort(key=lambda r: (-round((lambda b: (b[2] - b[0]) * (b[3] - b[1]))(bbox_mm(fps[r], crtyd(side))), 2),
                                 len(r), r))   # largest first; equal parts in reference order (D1, D2, D3)
        for r in refs:
            done.add(r)
            if not try_regions(fps[r], side, regions, pk):
                failed.append(f"{r}({name})")
                place_at(fps[r], 115.0, 95.0 + 3 * len(failed), 0)
        if name == "flash":   # memory decoupling claims its ball pairs before other parts use the strip
            done.update(place_mem_decaps(fps, pk, group_of))
    orient_parts(fps, group_of)
    face_north(fps, group_of)
    failed += hang_parts(fps, group_of, pk)
    done.update(r for r, f in fps.items() if any(group_of(f) == g and role_of(f) == role for g, role, _ in HANG))
    # 2-pin parts next to the pad they serve. Round 1: every group on its own side, close in.
    # Round 2 (leftovers): the other side close in, then own side further out, then the group's regions.
    # Doing all groups' own-side placement first keeps one group's overflow out of another's area.
    leftovers = []
    for name, side, regions in GROUPS:
        for r in sorted(r for r, f in fps.items() if r not in done and group_of(f) == name):
            done.add(r)
            fp = fps[r]
            pk.allow_shadow = name in SHADOW_OK
            target = find_anchor(fp, [f for f in fps.values() if f.GetReference() in done], group_of)
            if not (target and place_near(fp, side, target, pk, max_r=3.0, check=check_for(name))):
                leftovers.append((r, name, side, regions, target))
    for r, name, side, regions, target in leftovers:
        fp = fps[r]
        pk.allow_shadow = name in SHADOW_OK
        chk = check_for(name)
        other = "bottom" if side == "top" else "top"
        ok = target and (place_near(fp, other, target, pk, max_r=3.0, check=chk)
                         or place_near(fp, side, target, pk, max_r=10.0, check=chk))
        if not ok:
            set_side(fp, side)
            ok = try_regions(fp, side, regions, pk, check=chk)
        if not ok:
            failed.append(f"{r}({name})")
            place_at(fp, 115.0, 95.0 + 3 * len(failed), 0)
    pk.allow_shadow = False
    left = [r for r in fps if r not in done]
    board.Save(path)
    print("not in any group:", " ".join(left) or "none")
    print("did not fit:", " ".join(failed) or "none")


if __name__ == "__main__":
    main(sys.argv[1])
