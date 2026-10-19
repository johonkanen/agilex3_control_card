"""Tap vias: connect every SMD power/ground pad to its plane.

    squashfs-root/AppRun python3.11 -I tools/tap_vias.py hardware/control_card.kicad_pcb

Run after tools/power_pours.py (which clears all vias and tracks first) and the regulator cell
copper (tools/cell_copper.py cells), whose tracks the vias keep clear of. For each SMD pad on a
plane net that is not already on a via:
  - the via must land inside that net's plane: GND on L2/L5, +3V3/+0V75 on L4, +1V8/+1V2 on L3
    (inside the net's zone outline and not inside a higher-priority zone of another net there);
  - pads at least 0.45 mm on their narrow side get the via in the pad (filled and capped);
  - smaller pads (0201, SOT-563, TSSOP) get the nearest free spot just outside and a short stub;
  - via and stub keep clear of every other-net pad on both outer layers (including the BGA balls
    on the top), of every other via, and of the board edge;
  - large +0V75 pads (core inductor, output caps) get a second via;
  - no via of another net lands in a buck's input loop (the box around the regulator's VIN and GND
    pins and its input cap's pads): the two 3.3 V and core cells overlap top/bottom, and a +3V3 tap
    there once cut the core cell's GND pour off the regulator's GND pin.
Prints what could not be tapped. Zones are refilled afterwards (build_pcb.sh does it in DRC).
"""
import math
import sys
from collections import defaultdict

import pcbnew

MM = pcbnew.FromMM
BOARD = (75.2, 94.9, 107.738, 128.7)
EDGE = 0.3
VIA = (0.3, 0.15)          # pad, drill
CLR = 0.1                  # copper clearance (default net class)
CLR_SW = 0.15              # switch-node net class clearance
HOLE_GAP = 0.2             # hole to hole
HOLE_CLR = 0.2             # hole edge to any copper (board rule)
PTH_CLR = 0.28             # through-hole pad hole edge to other copper (JLCPCB multilayer minimum)


def clr_to(net):
    return CLR_SW if net.startswith("/Power/SW") else CLR


def via_keepout(net):
    """Distance from a via centre to another net's copper: pad clearance or hole clearance."""
    return max(VIA[0] / 2 + clr_to(net), VIA[1] / 2 + HOLE_CLR)
VIP_MIN = 0.45             # smallest pad dimension that takes a via-in-pad
PLANE_LAYERS = {"GND": ("In1.Cu", "In4.Cu"), "+3V3": ("In3.Cu",), "+0V75": ("In3.Cu",), "+1V8_HR": ("In2.Cu",),
                "+1V8": ("In2.Cu",), "+1V2": ("In2.Cu",)}
CELL = 1.0


def box(item):
    b = item.GetBoundingBox()
    return tuple(pcbnew.ToMM(v) for v in (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom()))


class Copper:
    """Spatial index of outer-layer pads and all vias, for clearance checks."""
    def __init__(self):
        self.grid = defaultdict(list)

    def add(self, kind, net, bb, layers):
        for i in range(int(bb[0] // CELL), int(bb[2] // CELL) + 1):
            for j in range(int(bb[1] // CELL), int(bb[3] // CELL) + 1):
                self.grid[(i, j)].append((kind, net, bb, layers))

    def near(self, x0, y0, x1, y1):
        seen = set()
        for i in range(int(x0 // CELL), int(x1 // CELL) + 1):
            for j in range(int(y0 // CELL), int(y1 // CELL) + 1):
                for it in self.grid.get((i, j), ()):
                    if id(it) not in seen:
                        seen.add(id(it))
                        yield it


def rect_dist(x, y, bb):
    dx = max(bb[0] - x, 0, x - bb[2])
    dy = max(bb[1] - y, 0, y - bb[3])
    return math.hypot(dx, dy)


LOOPS = []   # buck input-loop boxes, filled in main()


def via_ok(cu, x, y, net, own_pad_bb):
    r = VIA[0] / 2
    if net != "GND" and any(rect_dist(x, y, bb) < r + CLR for bb in LOOPS):
        return False
    x0, y0, x1, y1 = BOARD
    if not (x0 + EDGE + r <= x <= x1 - EDGE - r and y0 + EDGE + r <= y <= y1 - EDGE - r):
        return False
    for kind, n, bb, _ in cu.near(x - 1, y - 1, x + 1, y + 1):
        if kind == "via":
            cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
            if math.hypot(cx - x, cy - y) < (bb[2] - bb[0]) / 2 + r + max(CLR, HOLE_GAP) and n != net:
                return False
            if math.hypot(cx - x, cy - y) < VIA[1] + HOLE_GAP:   # hole to hole, any net
                return False
        elif kind == "pth":   # connector pin hole: its edge 0.28 mm from the via's copper
            cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
            if n != net and math.hypot(cx - x, cy - y) < (bb[2] - bb[0]) / 2 + r + PTH_CLR:
                return False
        elif n != net and bb is not own_pad_bb and rect_dist(x, y, bb) < via_keepout(n):
            return False
    return True


def stub_ok(cu, ax, ay, bx, by, w, net, layer):
    n = max(2, int(math.hypot(bx - ax, by - ay) / 0.05))
    for k in range(n + 1):
        x, y = ax + (bx - ax) * k / n, ay + (by - ay) * k / n
        for kind, nn, bb, layers in cu.near(x - 0.6, y - 0.6, x + 0.6, y + 0.6):
            if nn != net and layer in layers and rect_dist(x, y, bb) < w / 2 + clr_to(nn):
                return False
    return True


LAYER_ID = {}   # canonical layer name -> id, filled in main() (ZONE.GetLayerName() is unreliable)


def plane_here(zones, net, x, y):
    """True if one of this net's plane layers has its zone at (x, y), not overridden by a
    higher-priority zone of another net."""
    p = pcbnew.VECTOR2I(MM(x), MM(y))
    for layer in PLANE_LAYERS[net]:
        lid = LAYER_ID[layer]
        mine = [z for z in zones if z.GetLayer() == lid and z.GetNetname() == net and z.Outline().Contains(p)]
        if not mine:
            continue
        prio = max(z.GetAssignedPriority() for z in mine)
        if any(z.GetLayer() == lid and z.GetNetname() != net and z.GetAssignedPriority() > prio
               and z.Outline().Contains(p) for z in zones):
            continue
        return True
    return False


def main(path):
    board = pcbnew.LoadBoard(path)
    zones = list(board.Zones())
    for name in ("In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu"):
        LAYER_ID[name] = board.GetLayerID(name)
    fl, bl = board.GetLayerID("F.Cu"), board.GetLayerID("B.Cu")
    cu = Copper()
    pads = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if not pad.GetNumber():
                continue
            layers = {"F.Cu"} if pad.IsOnLayer(fl) else set()
            if pad.IsOnLayer(bl):
                layers.add("B.Cu")
            bb = box(pad)
            cu.add("pad", pad.GetNetname(), bb, layers)
            pads.append((fp, pad, bb, layers))
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                c, hr = pad.GetPosition(), pcbnew.ToMM(pad.GetDrillSize().x) / 2
                cx, cy = pcbnew.ToMM(c.x), pcbnew.ToMM(c.y)
                cu.add("pth", pad.GetNetname(), (cx - hr, cy - hr, cx + hr, cy + hr), {"F.Cu", "B.Cu"})
    for fp in board.GetFootprints():   # buck input loops: VIN (pin 3) and GND (pin 2) pins plus the 10u input cap
        if not fp.GetFPIDAsString().endswith("SOT-563"):
            continue
        group = fp.GetFieldText("Group")
        cin = [f for f in board.GetFootprints() if f.GetFieldText("Group") == group and f.GetValue() == "10u"]
        bbs = [box(p) for p in fp.Pads() if p.GetNumber() in ("2", "3")] + [box(p) for f in cin for p in f.Pads() if p.GetNumber()]
        LOOPS.append((min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs), max(b[3] for b in bbs)))
    tracks = board.Tracks()
    vias = [tracks[i] for i in range(len(tracks))]
    for v in vias:
        if v.GetClass() == "PCB_VIA":
            cu.add("via", v.GetNetname(), box(v), {"F.Cu", "B.Cu"})
        else:   # tracks (regulator cell copper is routed before the taps)
            lay = "F.Cu" if v.GetLayer() == fl else "B.Cu"
            cu.add("pad", v.GetNetname(), box(v), {lay})
    added, failed = 0, []
    for fp, pad, bb, layers in pads:
        net = pad.GetNetname()
        if net not in PLANE_LAYERS or pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
            continue
        if fp.GetReference() == "U1" or (sum(1 for p in fp.Pads() if p.GetNumber()) >= 24 and "BGA" in fp.GetFPIDAsString()):
            continue   # BGA balls: via-in-pad already placed by power_pours.py
        layer = "B.Cu" if "B.Cu" in layers else "F.Cu"
        cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
        if any(k == "via" and n == net and bx[0] <= cx <= bx[2] and bx[1] <= cy <= bx[3]
               for k, n, bx, _ in cu.near(bb[0], bb[1], bb[2], bb[3])):
            continue   # already sits on a via (decoupling on a BGA ball pair)
        want = 2 if net == "+0V75" and (bb[2] - bb[0]) * (bb[3] - bb[1]) >= 0.8 else 1
        spots = []
        if min(bb[2] - bb[0], bb[3] - bb[1]) >= VIP_MIN and plane_here(zones, net, cx, cy) and via_ok(cu, cx, cy, net, bb):
            spots.append((cx, cy, False))
        if len(spots) < want:
            cands = []
            for k in range(1, 25):
                d = k * 0.05
                for a in range(0, 360, 15):
                    x = cx + math.cos(math.radians(a)) * (max(bb[2] - bb[0], bb[3] - bb[1]) / 2 + d)
                    y = cy + math.sin(math.radians(a)) * (max(bb[2] - bb[0], bb[3] - bb[1]) / 2 + d)
                    cands.append((math.hypot(x - cx, y - cy), x, y))
            w = min(0.3, bb[2] - bb[0], bb[3] - bb[1])
            for _, x, y in sorted(cands):
                if len(spots) >= want:
                    break
                if any(math.hypot(x - sx, y - sy) < VIA[0] + HOLE_GAP for sx, sy, _ in spots):
                    continue
                if plane_here(zones, net, x, y) and via_ok(cu, x, y, net, bb) and stub_ok(cu, cx, cy, x, y, w, net, layer):
                    spots.append((x, y, True))
        if not spots:
            failed.append(f"{fp.GetReference()}.{pad.GetNumber()}[{net}]")
            continue
        for x, y, stub in spots:
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
            v.SetDrill(MM(VIA[1]))
            v.SetWidth(MM(VIA[0]))
            v.SetNet(pad.GetNet())
            board.Add(v)
            cu.add("via", net, (x - VIA[0] / 2, y - VIA[0] / 2, x + VIA[0] / 2, y + VIA[0] / 2), {"F.Cu", "B.Cu"})
            if stub:
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(pcbnew.VECTOR2I(MM(cx), MM(cy)))
                t.SetEnd(pcbnew.VECTOR2I(MM(x), MM(y)))
                t.SetWidth(MM(min(0.3, bb[2] - bb[0], bb[3] - bb[1])))
                t.SetLayer(board.GetLayerID(layer))
                t.SetNet(pad.GetNet())
                board.Add(t)
                lo = (min(cx, x) - 0.15, min(cy, y) - 0.15, max(cx, x) + 0.15, max(cy, y) + 0.15)
                cu.add("pad", net, lo, {layer})
            added += 1
    board.Save(path)
    print(f"{added} tap vias; not tapped ({len(failed)}): " + " ".join(failed))


if __name__ == "__main__":
    main(sys.argv[1])
