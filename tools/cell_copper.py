"""Regulator cell copper on the outer layers.

    squashfs-root/AppRun python3.11 -I tools/cell_copper.py hardware/control_card.kicad_pcb cells
    squashfs-root/AppRun python3.11 -I tools/cell_copper.py hardware/control_card.kicad_pcb leftover

"cells" runs after tools/power_pours.py and before tools/tap_vias.py (critical cell copper first,
vias around it); "leftover" runs after the taps. For each regulator/LDO cell (parts with the same Group field):
  - every net (except GND) shared by two or more of the cell's pads on its layer is connected with
    a minimum spanning tree of tracks (straight, else an L or a Z detour; narrower if the wide track
    does not fit). Widths: SW 0.6, +0V75 0.8, +5V/+1V8 0.6, +3V3 0.5, +1V2/+3V3A 0.4, others
    0.15 mm; the first/last 0.35 mm next to a small pad runs at the pad's narrow width (neck);
  - each buck cell gets a GND zone over its area, on its own layer (solid copper for the input-cap
    to IC ground loop; filled around everything else).
Then every plane-net SMD pad that still has no via and no track is routed to the nearest
same-net via or pad on its layer (pads over a plane of another net, crowded spots).
All copper keeps net-class clearance (0.15 mm to switch nodes, else 0.1 mm) from other nets and
0.2 mm from other-net drill holes (vias, through-hole pads).
Prints what could not be routed; DRC (build_pcb.sh) refills zones and checks.
"""
import math
import sys
from collections import defaultdict

import pcbnew

MM = pcbnew.FromMM
BOARD = (75.2, 94.9, 107.738, 128.7)
EDGE = 0.3
CELL = 1.0
HOLE_CLR = 0.2   # hole edge to other-net copper
PTH_CLR = 0.28   # through-hole pad hole edge to other-net copper (JLCPCB multilayer minimum)
CELLS = {"buck_core": "B.Cu", "buck_1v8": "B.Cu", "buck_3v3": "F.Cu", "ldo_1v2": "B.Cu", "ldo_1v8hr": "B.Cu",
         "ldo_analog": "B.Cu", "input_5v": "B.Cu"}
BUCKS = ("buck_core", "buck_1v8", "buck_3v3")
PLANE_NETS = ("GND", "+3V3", "+0V75", "+1V8", "+1V2", "+1V8_HR")


def width_for(net):
    if net.startswith("/Power/SW"):
        return 0.6
    return {"+0V75": 0.8, "+5V": 0.6, "+1V8": 0.6, "GND": 0.6, "+3V3": 0.5, "+1V2": 0.4,
            "+3V3A": 0.4}.get(net, 0.15)


def clr(net):
    return 0.15 if net.startswith("/Power/SW") else 0.1


def bbox(item):
    b = item.GetBoundingBox()
    return tuple(pcbnew.ToMM(v) for v in (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom()))


def rect_dist(x, y, bb):
    return math.hypot(max(bb[0] - x, 0, x - bb[2]), max(bb[1] - y, 0, y - bb[3]))


class Index:
    def __init__(self):
        self.g = defaultdict(list)

    def add(self, net, bb, layers, kind="rect", seg=None, w=0.0):
        it = (net, bb, layers, kind, seg, w)
        for i in range(int(bb[0] // CELL), int(bb[2] // CELL) + 1):
            for j in range(int(bb[1] // CELL), int(bb[3] // CELL) + 1):
                self.g[(i, j)].append(it)

    def near(self, x, y, r=0.8):
        seen = set()
        for i in range(int((x - r) // CELL), int((x + r) // CELL) + 1):
            for j in range(int((y - r) // CELL), int((y + r) // CELL) + 1):
                for it in self.g.get((i, j), ()):
                    if id(it) not in seen:
                        seen.add(id(it))
                        yield it


def seg_point_dist(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def seg_clear(idx, a, b, w, net, layer):
    x0, y0, x1, y1 = BOARD
    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.05))
    for k in range(n + 1):
        x, y = a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n
        if not (x0 + EDGE + w / 2 <= x <= x1 - EDGE - w / 2 and y0 + EDGE + w / 2 <= y <= y1 - EDGE - w / 2):
            return False
        for onet, bb, layers, kind, seg, ow in idx.near(x, y):
            if onet == net or layer not in layers:
                continue
            need = w / 2 + max(clr(net), clr(onet))
            d = seg_point_dist(x, y, *seg) - ow / 2 if kind == "seg" else rect_dist(x, y, bb)
            if d < need:
                return False
    # drill holes of other nets (vias, through-hole pads): 0.2 mm from the hole edge to the track edge
    for k in range(n + 1):
        x, y = a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n
        for onet, bb, layers, kind, seg, ow in idx.near(x, y):
            if kind in ("hole", "pth") and onet != net and \
                    math.hypot(x - seg[0], y - seg[1]) < w / 2 + (PTH_CLR if kind == "pth" else HOLE_CLR) + ow:
                return False
    return True


NECK = 0.35   # length of the narrow pad-exit section


def pieces(path, w, wa, wb):
    """Split a path into (p, q, width) pieces: the first/last NECK mm run at the pad width."""
    segs = list(zip(path, path[1:]))
    out = []
    for k, (p, q) in enumerate(segs):
        L = math.hypot(q[0] - p[0], q[1] - p[1])
        if L < 1e-9:
            continue
        ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
        start, stop = 0.0, L
        if k == 0 and wa < w:
            n = min(NECK, L)
            out.append((p, (p[0] + ux * n, p[1] + uy * n), wa))
            start = n
        if k == len(segs) - 1 and wb < w and stop - start > 0:
            n = min(NECK, stop - start)
            stop = L - n
        if stop > start:
            out.append(((p[0] + ux * start, p[1] + uy * start), (p[0] + ux * stop, p[1] + uy * stop), w))
        if k == len(segs) - 1 and wb < w and stop < L:
            out.append(((p[0] + ux * stop, p[1] + uy * stop), q, wb))
    return out


def route(idx, a, b, net, layer, wa=99.0, wb=99.0):
    """Straight, else L-shaped path from a to b; full width first, then narrower. wa/wb cap the
    width next to small pads (pad exit necks)."""
    w0 = width_for(net)
    for w in sorted({w0, max(0.25, w0 * 0.6), 0.15 if w0 <= 0.3 else 0.25}, reverse=True):
        paths = [[a, b], [a, (b[0], a[1]), b], [a, (a[0], b[1]), b]]
        for off in (0.0, 0.4, -0.4, 0.8, -0.8, 1.2, -1.2, 1.6, -1.6):   # Z detours (two bends)
            my = (a[1] + b[1]) / 2 + off
            mx = (a[0] + b[0]) / 2 + off
            paths += [[a, (a[0], my), (b[0], my), b], [a, (mx, a[1]), (mx, b[1]), b]]
        for path in paths:
            ps = pieces(path, w, min(w, wa), min(w, wb))
            if ps and all(seg_clear(idx, p, q, pw, net, layer) for p, q, pw in ps):
                return ps, w
    return None, None


def add_path(board, idx, ps, net_item, layer):
    for p, q, w in ps:
        if math.hypot(q[0] - p[0], q[1] - p[1]) < 1e-6:
            continue
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(MM(p[0]), MM(p[1])))
        t.SetEnd(pcbnew.VECTOR2I(MM(q[0]), MM(q[1])))
        t.SetWidth(MM(w))
        t.SetLayer(board.GetLayerID(layer))
        t.SetNet(net_item)
        board.Add(t)
        bb = (min(p[0], q[0]) - w / 2, min(p[1], q[1]) - w / 2, max(p[0], q[0]) + w / 2, max(p[1], q[1]) + w / 2)
        idx.add(net_item.GetNetname(), bb, {layer}, "seg", (p, q), w)


def pad_w(pad):
    """Narrow dimension of a pad: the widest track that can leave it without hitting neighbours."""
    s = pad.GetSize()
    return min(pcbnew.ToMM(s.x), pcbnew.ToMM(s.y))


def centre(pad):
    c = pad.GetPosition()
    return pcbnew.ToMM(c.x), pcbnew.ToMM(c.y)


def main(path, mode):
    board = pcbnew.LoadBoard(path)
    fl, bl = board.GetLayerID("F.Cu"), board.GetLayerID("B.Cu")
    idx = Index()
    pads = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if not pad.GetNumber():
                continue
            layers = ({"F.Cu"} if pad.IsOnLayer(fl) else set()) | ({"B.Cu"} if pad.IsOnLayer(bl) else set())
            idx.add(pad.GetNetname(), bbox(pad), layers)
            pads.append((fp, pad, layers))
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                c = centre(pad)
                r = pcbnew.ToMM(pad.GetDrillSize().x) / 2
                idx.add(pad.GetNetname(), (c[0] - r, c[1] - r, c[0] + r, c[1] + r), {"F.Cu", "B.Cu"}, "pth", c, r)
    tracks = board.Tracks()
    items = [tracks[i] for i in range(len(tracks))]
    vias, ends = [], defaultdict(set)
    for t in items:
        if t.GetClass() == "PCB_VIA":
            vias.append((t.GetNetname(), centre(t)))
            idx.add(t.GetNetname(), bbox(t), {"F.Cu", "B.Cu"})
            r = pcbnew.ToMM(pcbnew.Cast_to_PCB_VIA(t).GetDrillValue()) / 2 if hasattr(pcbnew, "Cast_to_PCB_VIA") else 0.075
            c = centre(t)
            idx.add(t.GetNetname(), (c[0] - r, c[1] - r, c[0] + r, c[1] + r), {"F.Cu", "B.Cu"}, "hole", c, r)
        else:
            s, e = t.GetStart(), t.GetEnd()
            lay = "F.Cu" if t.GetLayer() == fl else "B.Cu"
            for p in (s, e):
                ends[(t.GetNetname(), lay)].add((round(pcbnew.ToMM(p.x), 3), round(pcbnew.ToMM(p.y), 3)))
            idx.add(t.GetNetname(), bbox(t), {lay}, "seg",
                    ((pcbnew.ToMM(s.x), pcbnew.ToMM(s.y)), (pcbnew.ToMM(e.x), pcbnew.ToMM(e.y))),
                    pcbnew.ToMM(t.GetWidth()))
    failed, n_tracks = [], 0

    def connected(pad, layer):
        x, y = centre(pad)
        bb = bbox(pad)
        if any(n == pad.GetNetname() and bb[0] <= vx <= bb[2] and bb[1] <= vy <= bb[3] for n, (vx, vy) in vias):
            return True
        return any(bb[0] <= ex <= bb[2] and bb[1] <= ey <= bb[3] for ex, ey in ends[(pad.GetNetname(), layer)])

    # 1. cell nets: minimum spanning tree per net
    group_of = lambda f: f.GetFieldText("Group")   # noqa: E731
    for group, layer in (CELLS.items() if mode == "cells" else ()):
        cell = [(fp, pad) for fp, pad, layers in pads if group_of(fp) == group and layer in layers
                and pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
        nets = defaultdict(list)
        for fp, pad in cell:
            n = pad.GetNetname()
            # the core sense fallbacks' plane pads take their own via (tap pass): a track from the
            # output caps would cut through the divider
            if n in PLANE_NETS and any(q.GetNetname() in ("VCC_SENSE_P", "VCC_SENSE_N") for q in fp.Pads()):
                continue
            if n and not n.startswith("unconnected"):
                nets[n].append(pad)
        # widest (power) nets first; thin feedback/PG tracks then thread around them
        for net, plist in sorted(nets.items(), key=lambda kv: -width_for(kv[0])):
            if len(plist) < 2 or net == "GND":   # GND: every pad has its plane tap; the cell pour covers the loop
                continue
            # start the tree at the regulator pin if there is one (e.g. the FB pin), so the trunk leaves it first
            plist = sorted(plist, key=lambda p: "SOT-563" not in p.GetParentFootprint().GetFPIDAsString())
            pts = [centre(p) for p in plist]
            done, todo = [0], set(range(1, len(pts)))
            while todo:   # Prim: shortest edge from the tree, try to route it
                cands = sorted((math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]), i, j)
                               for i in done for j in todo)
                for _, i, j in cands:
                    ps, w = route(idx, pts[i], pts[j], net, layer, pad_w(plist[i]), pad_w(plist[j]))
                    if ps:
                        add_path(board, idx, ps, plist[0].GetNet(), layer)
                        n_tracks += len(ps)
                        for p, q, _ in ps:
                            ends[(net, layer)].update({(round(p[0], 3), round(p[1], 3)), (round(q[0], 3), round(q[1], 3))})
                        done.append(j)
                        todo.discard(j)
                        break
                else:
                    failed += [f"{group}:{net}:{plist[j].GetParentFootprint().GetReference()}.{plist[j].GetNumber()}"
                               for j in todo]
                    break
        if group in BUCKS:   # GND pour over the cell area, on the cell's layer
            # courtyards, not GetBoundingBox(): that includes the parts' text (an 11 mm value field on the 1.8 V buck
            # once stretched this pour over the ADC B area)
            boxes = []
            for fp in board.GetFootprints():
                if group_of(fp) == group:
                    cy = fp.GetCourtyard(pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd).BBox()
                    boxes.append(bbox(fp) if cy.GetWidth() == 0 else
                                 tuple(pcbnew.ToMM(v) for v in (cy.GetLeft(), cy.GetTop(), cy.GetRight(), cy.GetBottom())))
            x0 = min(b[0] for b in boxes) - 0.2
            y0 = min(b[1] for b in boxes) - 0.2
            x1 = max(b[2] for b in boxes) + 0.2
            y1 = max(b[3] for b in boxes) + 0.2
            z = pcbnew.ZONE(board)
            z.SetLayer(board.GetLayerID(layer))
            z.SetNet(board.FindNet("GND"))
            z.SetAssignedPriority(0)
            z.SetMinThickness(MM(0.2))
            z.SetLocalClearance(MM(0.15))
            z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
            o = z.Outline()
            o.NewOutline()
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                o.Append(MM(x), MM(y))
            board.Add(z)
    # 2. leftover plane-net pads: route to the nearest same-net via or pad on the same layer
    for fp, pad, layers in (pads if mode == "leftover" else ()):
        net = pad.GetNetname()
        if net not in PLANE_NETS or pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
            continue
        if fp.GetReference() == "U1" or "BGA" in fp.GetFPIDAsString():
            continue
        layer = "B.Cu" if "B.Cu" in layers else "F.Cu"
        if connected(pad, layer):
            continue
        a = centre(pad)
        targets = [p for n, p in vias if n == net] + [centre(q) for f2, q, l2 in pads if q.GetNetname() == net
                                                      and layer in l2 and q != pad and f2.GetReference() != "U1"
                                                      and connected(q, layer)]
        for b in sorted(targets, key=lambda p: math.hypot(p[0] - a[0], p[1] - a[1]))[:8]:
            if math.hypot(b[0] - a[0], b[1] - a[1]) > 6.0:
                break
            ps, w = route(idx, a, b, net, layer, pad_w(pad))
            if ps:
                add_path(board, idx, ps, pad.GetNet(), layer)
                n_tracks += len(ps)
                for p, q, _ in ps:
                    ends[(net, layer)].update({(round(p[0], 3), round(p[1], 3)), (round(q[0], 3), round(q[1], 3))})
                break
        else:
            failed.append(f"leftover:{net}:{fp.GetReference()}.{pad.GetNumber()}")
    board.Save(path)
    print(f"{mode}: {n_tracks} track segments" + (f", GND pours on {len(BUCKS)} buck cells" if mode == "cells" else "")
          + f"; not routed ({len(failed)}): "
          + " ".join(failed))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "cells")
