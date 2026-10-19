"""Power distribution copper: BGA via-in-pad fan-out for supply/ground balls, and the plane zones.

    squashfs-root/AppRun python3.11 -I tools/power_pours.py hardware/control_card.kicad_pcb

Removes all zones, vias and track segments first, so it is only for generated boards (build_pcb.sh).

Vias: 0.25/0.15 mm via-in-pad (filled and capped) on every supply, ground and sense ball of the
FPGA, HyperRAM and flash, except balls under a bottom-side pad of another net (the 1.8 V cell
covers a few FPGA GND balls; those connect on L1 instead).

Zones (KiCad In1..In4 = L2..L5), see docs/design-notes.md "Power distribution plan":
  L2, L5   GND, whole board
  L3       +1V2 island (north edge + east column of the power block, east to the 1.2 V LDO),
           +1V8 (from the 1.8 V buck across the BGA's west half to the power block, plus a
           north arm under the flash, HyperRAM and JTAG shifter); +1V2 has priority
  L4       +0V75 island (core ball block + a block east to the core buck output caps), +3V3 fills the rest
           and is open for signal routing
Prints a per-net connectivity summary after filling.
"""
import sys

import pcbnew

MM = pcbnew.FromMM
BOARD = (75.2, 94.9, 107.738, 128.7)
VIA_NETS = ("GND", "VCC_SENSE_P", "VCC_SENSE_N")
BGA_VIA = (0.25, 0.15)     # pad, drill
VIA_KEEPOUT = 0.1          # copper clearance from a via pad to another net's pad

ZONES = [
    # (layer, net, priority, polygon)
    ("In1.Cu", "GND", 0, [BOARD[:2], (BOARD[2], BOARD[1]), BOARD[2:], (BOARD[0], BOARD[3])]),
    ("In4.Cu", "GND", 0, [BOARD[:2], (BOARD[2], BOARD[1]), BOARD[2:], (BOARD[0], BOARD[3])]),
    ("In3.Cu", "+3V3", 1, [BOARD[:2], (BOARD[2], BOARD[1]), BOARD[2:], (BOARD[0], BOARD[3])]),
    # +0V75 only under the BGA's core ball block and its bottom decaps, plus a block east to x 102.3 under the
    # core buck's output caps (the cell faces the FPGA, so the island never runs under the switcher or
    # inductor); the rest of L4 is +3V3 and free for routing.
    ("In3.Cu", "+0V75", 2, [(90.4, 110.6), (97.9, 110.6), (97.9, 109.3), (102.3, 109.3), (102.3, 118.6), (90.4, 118.6)]),
    # south edge stops at y 123.0: the strip below it on L3 is kept for the 5 V run to the left side;
    # the band y 119.2-123.0 reaches the SDM strap/config pull-ups and stops at x 105.6, which leaves L3's east
    # strip (x 105.6-107.4, up past the +1V2 island) for the +5V run from J1 pin 1 north to the bucks
    # the notch x 85.2-92.5, y 96.4-103.6 covers the 1.8 V HyperRAM and its decaps/pull-up (bottom side)
    ("In2.Cu", "+1V8", 2, [(81.6, 103.6), (85.2, 103.6), (85.2, 96.4), (92.5, 96.4), (92.5, 95.5), (101.8, 95.5), (101.8, 119.2),
                           (105.6, 119.2), (105.6, 123.0), (81.6, 123.0)]),
    # bank 6C (HyperRAM, clock) has its own 1.8 V (+1V8_HR, power group 2B): an island over the HyperRAM area of the
    # +1V8 pour with a 1.6 mm strip south to the bank's VCCIO balls U17/W15; the +1V8 pour flows around it
    ("In2.Cu", "+1V8_HR", 3, [(85.2, 96.4), (92.5, 96.4), (92.5, 103.6), (89.8, 103.6), (89.8, 111.6), (88.2, 111.6),
                              (88.2, 103.6), (85.2, 103.6)]),
    ("In2.Cu", "+1V2", 3, [(91.15, 109.05), (95.9, 109.05), (95.9, 111.4), (105.3, 111.4), (105.3, 119.2),
                           (97.0, 119.2), (97.0, 116.4), (95.0, 116.4), (95.0, 110.75), (91.15, 110.75)]),
]


def needs_via(net):
    return net in VIA_NETS or net.startswith("+")


def pad_box(pad):
    bb = pad.GetBoundingBox()
    return tuple(pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))


def strip_blocks(path, heads=("via", "zone", "segment")):
    """Remove top-level (via ...), (zone ...) and (segment ...) blocks from the board file. Done on the text
    because KiCad 10's Python binding cannot reliably iterate a board's tracks/zones for removal."""
    t = open(path).read()
    out, i = [], 0
    while True:
        j = min([k for k in (t.find(f"\n\t({h}\n", i) for h in heads) if k >= 0] or [-1])
        if j < 0:
            out.append(t[i:])
            break
        out.append(t[i:j])
        depth, k = 0, j + 2
        while True:
            c = t[k]
            if c == '"':
                k = t.index('"', k + 1)
                while t[k - 1] == "\\":
                    k = t.index('"', k + 1)
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        i = k + 1
    open(path, "w", newline="\n").write("".join(out))


def main(path):
    strip_blocks(path)
    board = pcbnew.LoadBoard(path)
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    bottom_pads = [(p.GetNetname(), pad_box(p)) for f in fps.values() if f.IsFlipped() and f.GetReference() not in ("U1",)
                   for p in f.Pads() if p.GetNumber()]
    r = BGA_VIA[0] / 2 + VIA_KEEPOUT
    bgas = [f for f in fps.values() if sum(1 for p in f.Pads() if p.GetNumber()) >= 24 and "BGA" in f.GetFPIDAsString()
            or f.GetReference() == "U1"]
    added, skipped = 0, []
    for bga in bgas:
        for pad in bga.Pads():
            net = pad.GetNetname()
            if not needs_via(net):
                continue
            c = pad.GetPosition()
            x, y = pcbnew.ToMM(c.x), pcbnew.ToMM(c.y)
            hit = next((n for n, b in bottom_pads if n != net and b[0] - r < x < b[2] + r and b[1] - r < y < b[3] + r), None)
            if hit is not None:
                skipped.append(f"{bga.GetReference()}.{pad.GetNumber()}[{net}] under {hit}")
                continue
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(c)
            v.SetDrill(MM(BGA_VIA[1]))
            v.SetWidth(MM(BGA_VIA[0]))
            v.SetNet(pad.GetNet())
            board.Add(v)
            added += 1
    for layer, net, prio, poly in ZONES:
        z = pcbnew.ZONE(board)
        z.SetLayer(board.GetLayerID(layer))
        z.SetNet(board.FindNet(net))
        z.SetAssignedPriority(prio)
        z.SetMinThickness(MM(0.15))
        z.SetLocalClearance(MM(0.15))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        o = z.Outline()
        o.NewOutline()
        for x, y in poly:
            o.Append(MM(x), MM(y))
        board.Add(z)
    board.BuildConnectivity()
    if not pcbnew.ZONE_FILLER(board).Fill(board.Zones()):
        print("warning: zone fill reported a problem")
    board.Save(path)
    print(f"{added} via-in-pad vias; skipped {len(skipped)} (pad of another net on the bottom): " + ", ".join(skipped))
    for layer, net, prio, poly in ZONES:
        zs = [z for z in board.Zones() if z.GetLayerName() == layer and z.GetNetname() == net]
        area = sum(z.CalculateFilledArea() for z in zs) / 1e12   # nm^2 -> mm^2
        islands = sum(z.GetFilledPolysList(board.GetLayerID(layer)).OutlineCount() for z in zs)
        print(f"  {layer:7} {net:6} filled {area:7.1f} mm2 in {islands} piece(s)")


if __name__ == "__main__":
    main(sys.argv[1])
