"""Route the trace-routed supply rails: +5V and the analog supply +3V3A.

    squashfs-root/AppRun python3.11 -I tools/route_rails.py hardware/control_card.kicad_pcb

Grid router (0.1 mm grid unless a rail sets its own, Dijkstra), one rail at a time in RAILS order; each rail's copper is an
obstacle for the next: the 3.3 V feedback node, the core sense pair, the FPGA GND balls under
the 1.8 V cell, the core power-good link, +5V, the 1.8 V power-good link, then
+3V3A. Per rail: the layers it may use, a track width per layer, a narrower neck
where the full width does not fit (pad exits, via fields), per-layer cost factors and a via size.

  +5V     F.Cu, L3 (In2.Cu) and B.Cu from J1 pin 1. L3 only outside the +1V8/+1V2 pours (the
          reserved south strip and the west edge), 0.8 mm there (inner copper is 0.5 oz), 0.6 mm
          outside; L3 is cheapest and F.Cu dearest, since L1 is kept for the FPGA I/O.
  +3V3A   from the analog LDO output U6.5 to both ADC chains: muxes, buffers, ADC AVDD and their caps
          The analog rails stay on the outer layers over the L2/L5 ground planes, away from the
          digital supplies on L3/L4.

After each rail, a rip-up and reroute pass (refine) takes out each link it added, most expensive first,
and rejoins the pieces against the finished tree, keeping the cheaper result.

Clearances: net class (0.15 mm to switch nodes, else 0.1 mm) plus a 0.03 mm grid margin, 0.2 mm
from drill holes, 0.3 mm from the board edge. The rail's copper already on the board (pads, cell
tracks) is grouped into connected pieces; from the piece holding the root pad, the nearest
unconnected piece is routed into the tree until all are joined. Existing same-net copper lifts the
blocking only where the new track stays inside it. Run after tools/cell_copper.py (leftover pass).
"""
import heapq
import math
import sys

import pcbnew

MM = pcbnew.FromMM
BOARD = (75.2, 94.9, 107.738, 128.7)
EDGE = 0.3
HOLE_CLR = 0.2
PTH_CLR = 0.28                      # through-hole pad hole edge to other copper (JLCPCB multilayer minimum)
MARGIN = 0.03                       # grid slack: diagonal steps between checked cells
NECK_COST = 3                       # cost multiplier on neck-only cells
VIA_COST = 20                       # in grid steps (2 mm)
HUG_COST = 3                        # cost factor off the partner track of a coupled pair
ESCAPE = 0.3                        # extra via keep-out around fine-pitch IC pads
PLANE_LAYERS = {"GND": ("In1.Cu", "In4.Cu"), "+3V3": ("In3.Cu",), "+0V75": ("In3.Cu",), "+1V8_HR": ("In2.Cu",),
                "+1V8": ("In2.Cu",), "+1V2": ("In2.Cu",)}

RAILS = [
    # the 3.3 V feedback node first: R9's +3V3 pad sits between the divider's FB pads
    dict(net="/Power/FB_3V3", root="U4.1", width={"F.Cu": 0.2, "B.Cu": 0.2}, neck=0.1,
         cost={"F.Cu": 1.0, "B.Cu": 2.0}, via=(0.3, 0.15), sw_keepaway=0.3),
    # core remote sense: a pair on L6 from the FPGA's VCCLSENSE/GNDSENSE via-in-pads to the divider,
    # kept 0.5 mm further from the switch node. The P ball is north of the N ball, and place.py
    # stacks the divider the same way (VCC_SENSE_P resistor above, sense pads facing west), so the
    # pair needs no crossing; VCC_SENSE_N follows VCC_SENSE_P on its south side. The channels between
    # the 0.75 x 0.77 mm pitch via-in-pads leave the track centre a 0.04-0.06 mm window, so the pair
    # uses a 0.05 mm grid through the ball-row midlines next to the sense balls.
    dict(net="VCC_SENSE_P", root="U1.AH33", width={"B.Cu": 0.15}, neck=0.1, cost={"B.Cu": 1.0},
         via=None, sw_keepaway=0.5, grid=(0.05, (94.25, 113.77))),
    dict(net="VCC_SENSE_N", root="U1.AL33", width={"B.Cu": 0.15}, neck=0.1, cost={"B.Cu": 1.0},
         via=None, sw_keepaway=0.5, hug="VCC_SENSE_P", grid=(0.05, (94.25, 113.77))),
    # FPGA GND balls under the 1.8 V cell (no via-in-pad there): out on L1 to a GND ball with a via or
    # to a new via; the corner's balls are on a 0.65 mm pitch, so a 0.05 mm grid on their midlines
    dict(net="GND", plane=True, width={"F.Cu": 0.2, "B.Cu": 0.3}, neck=0.1,
         cost={"F.Cu": 1.0, "B.Cu": 2.0}, via=(0.3, 0.15), grid=(0.05, (85.211, 104.911))),
    # bead-filtered FPGA supplies (VCCPLLDIG_SDM, VCCPLL_SDM, VCCADC, VCCRCORE) and the oscillator supply:
    # from the ball's via-in-pad (or the oscillator pin) to its 1 uF, 47 uF and bead on L6, or where the
    # decap field under the BGA closes L6, a short stub on L3 that the +1V8/+1V2 pours flow around; the
    # bead's supply side is tapped to its plane like any other supply pad
    *[dict(net=n, root=r, width={"B.Cu": 0.2, "In2.Cu": 0.2}, neck=0.1, cost={"B.Cu": 1.0, "In2.Cu": 2.0},
           via=(0.3, 0.15), grid=(0.05, (94.25, 113.77)))
      for n, r in (("+0V75_PLLDIG", "U1.BB30"), ("+1V8_PLL", "U1.BB38"), ("+1V8_ADC", "U1.AT36"),
                   ("+1V2_RCORE", "U1.AB38"), ("+1V8_OSC", "X1.4"))],
    # power-good sequencing links across the board: core PG -> 1.8 V EN, 1.8 V PG -> 3.3 V EN.
    # Mostly L6, which is freer than L1 (the FPGA I/O escape layer); they cross under the BGA between its
    # via-in-pads, so the sense pair's 0.05 mm ball-midline grid. No extra switch-node keep-away: each EN pin
    # sits 0.5 mm from its buck's SW pin and would be sealed in. They go after the sense pair, so they go
    # round the divider instead of enclosing it; the core link also goes before +5V, whose way to the
    # pull-up R5 would otherwise close the cell's south exit. The two links are crossed (U3.5 above U3.6,
    # but U2 is south of U4), so the second one changes layer
    dict(net="/Power/PG_0V75", root="U2.6", width={"F.Cu": 0.15, "B.Cu": 0.15}, neck=0.1,
         cost={"F.Cu": 3.0, "B.Cu": 1.0}, via=(0.3, 0.15), grid=(0.05, (94.25, 113.77))),
    dict(net="+5V", root="J1.1", width={"F.Cu": 0.6, "In2.Cu": 0.8, "B.Cu": 0.6}, neck=0.3,
         cost={"F.Cu": 5.0, "In2.Cu": 1.0, "B.Cu": 2.0}, via=(0.45, 0.25), inner_keep_out=("+1V8", "+1V2")),
    dict(net="/Power/PG_1V8", root="U3.6", width={"F.Cu": 0.15, "B.Cu": 0.15}, neck=0.1,
         cost={"F.Cu": 3.0, "B.Cu": 1.0}, via=(0.3, 0.15), grid=(0.05, (94.25, 113.77))),
    # ADC B's analog path (bottom): buffer output -> kickback R -> AINP, before +3V3A so the analog supply does not take
    # the 1-2 mm between the buffer, R30 and the ADC (ADC A's are on L1 and route in the signal pass)
    *[dict(net=n, root=r, width={"B.Cu": 0.2, "F.Cu": 0.2}, neck=0.1, cost={"B.Cu": 1.0, "F.Cu": 4.0}, via=(0.3, 0.15))
      for n, r in (("/ADC/BUFB_OUT", "U14.1"), ("/ADC/AINP_B", "U15.7"))],
    dict(net="+3V3A", root="U6.5", width={"F.Cu": 0.4, "B.Cu": 0.4}, neck=0.2,
         cost={"F.Cu": 1.5, "B.Cu": 1.0}, via=(0.3, 0.15)),
    # plane-net pads the tap pass could not give a via: routed to the nearest copper that reaches the
    # plane, or to a new via where the plane is
    *[dict(net=n, plane=True, width={"F.Cu": 0.3, "B.Cu": 0.3}, neck=0.15,
           cost={"F.Cu": 1.0, "B.Cu": 1.0}, via=(0.3, 0.15)) for n in ("+3V3", "+1V8", "+1V2", "+0V75", "+1V8_HR")],
]


def clr(net):
    return (0.15 if net.startswith("/Power/SW") else 0.1) + MARGIN


class Grid:
    """Track-centre grid over the board. step and origin are per rail: the origin is a point the grid
    passes through, e.g. a channel midline between BGA balls."""
    def __init__(self, step=0.1, origin=(BOARD[0], BOARD[1])):
        self.step = step
        self.x0 = origin[0] - math.ceil((origin[0] - BOARD[0]) / step - 1e-9) * step
        self.y0 = origin[1] - math.ceil((origin[1] - BOARD[1]) / step - 1e-9) * step
        self.nx = int((BOARD[2] - self.x0) / step) + 1
        self.ny = int((BOARD[3] - self.y0) / step) + 1

    def ij(self, x, y):
        return int(round((x - self.x0) / self.step)), int(round((y - self.y0) / self.step))

    def xy(self, i, j):
        return self.x0 + i * self.step, self.y0 + j * self.step

    def cells_near(self, x0, y0, x1, y1):
        s = self.step
        i0, j0 = max(0, int((x0 - self.x0) / s)), max(0, int((y0 - self.y0) / s))
        i1, j1 = min(self.nx - 1, int((x1 - self.x0) / s) + 1), min(self.ny - 1, int((y1 - self.y0) / s) + 1)
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                yield i, j


def seg_dist(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def mm(v):
    return pcbnew.ToMM(v)


def route(board, rail, quiet=False):
    """Join the rail's pieces; returns (links, failed), a link being dict(cost, items) of the copper it added."""
    NET, WIDTH, NECK, LAYER_COST = rail["net"], rail["width"], rail["neck"], rail["cost"]
    VIA = rail.get("via") or (0, 0)   # None: a single-layer rail, no vias
    ALL = ("F.Cu", "In2.Cu", "B.Cu")
    LAYERS = [L for L in ALL if L in WIDTH]

    def cl(onet):   # clearance to another net's copper
        c = max(clr(NET), clr(onet))
        if onet.startswith("/Power/SW"):
            c += rail.get("sw_keepaway", 0)
        return c
    lid = {n: board.GetLayerID(n) for n in ("F.Cu", "In2.Cu", "B.Cu")}
    g = Grid(*rail.get("grid", ()))
    STEP = g.step
    N = g.nx * g.ny
    blocked = {L: bytearray(N) for L in LAYERS}   # full-width track centre not allowed
    narrow = {L: bytearray(N) for L in LAYERS}    # not even a neck-width track centre
    via_bad = bytearray(N)                         # via centre not allowed
    # cells where a track centre stays inside existing +5V copper (the copper eroded by half the
    # full width, or by half the neck width); there the other-net blocking does not apply
    mine_w = {L: bytearray(N) for L in LAYERS}
    mine_n = {L: bytearray(N) for L in LAYERS}

    def mark_mine(L, kind, geom):
        for arr, e in ((mine_w[L], WIDTH[L] / 2), (mine_n[L], NECK / 2)):
            if kind == "rect":
                x0, y0, x1, y1 = geom
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                if min(x1 - x0, y1 - y0) < 2 * e - 0.01:   # pad narrower than the track: end on its centre only
                    x0 = x1 = cx
                    y0 = y1 = cy
                x0, x1 = (x0 + e, x1 - e) if x1 - x0 > 2 * e else (cx, cx)
                y0, y1 = (y0 + e, y1 - e) if y1 - y0 > 2 * e else (cy, cy)
                for i, j in g.cells_near(x0 - STEP, y0 - STEP, x1 + STEP, y1 + STEP):
                    x, y = g.xy(i, j)
                    if x0 - STEP / 2 <= x <= x1 + STEP / 2 and y0 - STEP / 2 <= y <= y1 + STEP / 2:
                        mark(arr, i, j)
            elif kind == "circ":
                (cx, cy), r = geom
                if r < e:   # narrower than the track: no override
                    continue
                r = max(r - e, STEP / 2)
                for i, j in g.cells_near(cx - r, cy - r, cx + r, cy + r):
                    x, y = g.xy(i, j)
                    if math.hypot(x - cx, y - cy) <= r:
                        mark(arr, i, j)
            else:
                (a, b), w = geom
                if w / 2 < e:
                    continue
                r = max(w / 2 - e, STEP / 2)
                for i, j in g.cells_near(min(a[0], b[0]) - r, min(a[1], b[1]) - r, max(a[0], b[0]) + r, max(a[1], b[1]) + r):
                    x, y = g.xy(i, j)
                    if seg_dist(x, y, a, b) <= r:
                        mark(arr, i, j)

    def mark(arr, i, j):
        arr[i * g.ny + j] = 1

    def block_shape(layers, kind, geom, onet, escape=0.0):
        """Mark cells too close to another net's copper. kind: rect (bbox), seg ((a, b), w), circ ((c), r), hole."""
        for L in layers:
            if L not in LAYERS:
                continue
            c = cl(onet)
            _rast(L, kind, geom, WIDTH[L] / 2 + c, blocked[L])
            _rast(L, kind, geom, NECK / 2 + c, narrow[L])
        vneed = VIA[0] / 2 + cl(onet) + escape
        _rast(None, kind, geom, vneed, via_bad)

    def _rast(L, kind, geom, need, arr):
        if kind == "rect":
            x0, y0, x1, y1 = geom
            for i, j in g.cells_near(x0 - need, y0 - need, x1 + need, y1 + need):
                x, y = g.xy(i, j)
                if math.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1)) < need:
                    mark(arr, i, j)
        elif kind == "seg":
            (a, b), w = geom
            r = need + w / 2
            for i, j in g.cells_near(min(a[0], b[0]) - r, min(a[1], b[1]) - r, max(a[0], b[0]) + r, max(a[1], b[1]) + r):
                x, y = g.xy(i, j)
                if seg_dist(x, y, a, b) < r:
                    mark(arr, i, j)
        else:   # circ / hole: geom = ((cx, cy), radius)
            (cx, cy), rr = geom
            r = need + rr
            for i, j in g.cells_near(cx - r, cy - r, cx + r, cy + r):
                x, y = g.xy(i, j)
                if math.hypot(x - cx, y - cy) < r:
                    mark(arr, i, j)

    # board edge
    for L in LAYERS:
        m = EDGE + WIDTH[L] / 2
        for i in range(g.nx):
            for j in range(g.ny):
                x, y = g.xy(i, j)
                if x < BOARD[0] + m or x > BOARD[2] - m or y < BOARD[1] + m or y > BOARD[3] - m:
                    mark(blocked[L], i, j)
                m2 = EDGE + NECK / 2
                if x < BOARD[0] + m2 or x > BOARD[2] - m2 or y < BOARD[1] + m2 or y > BOARD[3] - m2:
                    mark(narrow[L], i, j)
    for i in range(g.nx):
        for j in range(g.ny):
            x, y = g.xy(i, j)
            if x < BOARD[0] + EDGE + VIA[0] / 2 or x > BOARD[2] - EDGE - VIA[0] / 2 or \
                    y < BOARD[1] + EDGE + VIA[0] / 2 or y > BOARD[3] - EDGE - VIA[0] / 2:
                mark(via_bad, i, j)
    # In2: stay out of the +1V8/+1V2 pours
    zones = [z for z in board.Zones() if "In2.Cu" in LAYERS and z.GetLayer() == lid["In2.Cu"]
             and z.GetNetname() in rail.get("inner_keep_out", ())]
    for i in range(g.nx):
        for j in range(g.ny):
            x, y = g.xy(i, j)
            p = pcbnew.VECTOR2I(MM(x), MM(y))
            if any(z.Outline().Contains(p) for z in zones):
                mark(blocked["In2.Cu"], i, j)
                mark(narrow["In2.Cu"], i, j)
    # copper
    items = []   # (+5V items for connectivity): (kind, layers, geom)
    for fp in board.GetFootprints():
        two = [p for p in fp.Pads() if p.GetNumber()]
        if len(two) == 2 and all(p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD for p in two):
            # no track between the two pads of a passive (under its body); the body box is the
            # span between the pads' facing edges
            bs = [p.GetBoundingBox() for p in two]
            x0 = mm(max(min(b.GetLeft() for b in bs), min(b.GetRight() for b in bs)))
            x1 = mm(max(b.GetLeft() for b in bs))
            y0 = mm(max(min(b.GetTop() for b in bs), min(b.GetBottom() for b in bs)))
            y1 = mm(max(b.GetTop() for b in bs))
            ly = [L for L in ("F.Cu", "B.Cu") if two[0].IsOnLayer(lid[L]) and L in LAYERS]
            if x1 > x0:   # pads side by side: the gap spans x0..x1 over the pads' height
                gap = (x0, mm(min(b.GetTop() for b in bs)), x1, mm(max(b.GetBottom() for b in bs)))
            elif y1 > y0:
                gap = (mm(min(b.GetLeft() for b in bs)), y0, mm(max(b.GetRight() for b in bs)), y1)
            else:
                gap = None
            if gap:
                for L in ly:
                    _rast(L, "rect", gap, NECK / 2, narrow[L])
                    _rast(L, "rect", gap, WIDTH[L] / 2, blocked[L])
        # fine-pitch ICs (SOT-563, QFN): vias of other nets stay ESCAPE further out, so the pins
        # keep a way out (a +5V via once sealed the 3.3 V buck's EN pin)
        cs = [p.GetPosition() for p in fp.Pads() if p.GetNumber()]
        fine = len(cs) >= 5 and fp.GetReference() != "U1" and any(
            0 < math.hypot(mm(a.x - b.x), mm(a.y - b.y)) <= 0.55 for a in cs for b in cs)
        for pad in fp.Pads():
            if not pad.GetNumber():
                continue
            b = pad.GetBoundingBox()
            box = (mm(b.GetLeft()), mm(b.GetTop()), mm(b.GetRight()), mm(b.GetBottom()))
            tht = pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
            # connectivity uses the pad's real layers; routing only the rail's own
            layers = ALL if tht else [L for L in ("F.Cu", "B.Cu") if pad.IsOnLayer(lid[L])]
            if pad.GetNetname() == NET:
                items.append(("rect", layers, box, f"{fp.GetReference()}.{pad.GetNumber()}"))
                for L in layers:
                    if L in LAYERS:
                        mark_mine(L, "rect", box)
            else:
                block_shape(layers, "rect", box, pad.GetNetname(), ESCAPE if fine else 0.0)
            if tht:
                c = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
                dr = mm(pad.GetDrillSize().x) / 2
                if pad.GetNetname() != NET:
                    for L in LAYERS:
                        _rast(L, "circ", (c, dr), WIDTH[L] / 2 + PTH_CLR + MARGIN, blocked[L])
                        _rast(L, "circ", (c, dr), NECK / 2 + PTH_CLR + MARGIN, narrow[L])
                _rast(None, "circ", (c, dr), max(VIA[1] / 2 + HOLE_CLR, VIA[0] / 2 + PTH_CLR), via_bad)
    tracks = board.Tracks()
    for k in range(len(tracks)):
        t = tracks[k]
        if t.GetClass() == "PCB_VIA":
            t = pcbnew.Cast_to_PCB_VIA(t)   # the uncast GetWidth() has no via size
            c = (mm(t.GetPosition().x), mm(t.GetPosition().y))
            r = mm(t.GetWidth(lid["F.Cu"])) / 2
            dr = mm(t.GetDrillValue()) / 2
            if t.GetNetname() == NET:
                items.append(("circ", ALL, (c, r), "via"))
                for L in LAYERS:
                    mark_mine(L, "circ", (c, r))
            else:
                block_shape(LAYERS, "circ", (c, r), t.GetNetname())
                for L in LAYERS:
                    _rast(L, "circ", (c, dr), WIDTH[L] / 2 + HOLE_CLR + MARGIN, blocked[L])
                    _rast(L, "circ", (c, dr), NECK / 2 + HOLE_CLR + MARGIN, narrow[L])
            _rast(None, "circ", (c, dr), VIA[1] / 2 + HOLE_CLR + 0.0, via_bad)
        else:
            a = (mm(t.GetStart().x), mm(t.GetStart().y))
            b = (mm(t.GetEnd().x), mm(t.GetEnd().y))
            w = mm(t.GetWidth())
            L = next((n for n in LAYERS if t.GetLayer() == lid[n]), None)
            if L is None:   # a layer this rail does not use: only its vias must keep clear
                if t.GetNetname() != NET:
                    _rast(None, "seg", ((a, b), w), VIA[0] / 2 + cl(t.GetNetname()), via_bad)
                continue
            if t.GetNetname() == NET:
                items.append(("seg", [L], ((a, b), w), "track"))
                mark_mine(L, "seg", ((a, b), w))
            else:
                block_shape([L], "seg", ((a, b), w), t.GetNetname())

    plane = rail.get("plane")
    plane_ok = None
    if plane:
        # the net's own pours on the routing layers (buck cell GND pours) connect what lies in them
        for z in board.Zones():
            L = next((n for n in LAYERS if z.GetLayer() == lid[n]), None)
            if L is not None and z.GetNetname() == NET:
                items.append(("zone", [L], z, "pour"))
        # where a new via lands in the net's plane: inside its zone on a plane layer and not under a
        # higher-priority zone of another net there (as in tap_vias.py)
        pl = [board.GetLayerID(n) for n in PLANE_LAYERS[NET]]
        zs = [z for z in board.Zones() if z.GetLayer() in pl]
        plane_ok = bytearray(N)
        for i in range(g.nx):
            for j in range(g.ny):
                if via_bad[i * g.ny + j]:
                    continue
                x, y = g.xy(i, j)
                p = pcbnew.VECTOR2I(MM(x), MM(y))
                for lay in pl:
                    mine_z = [z for z in zs if z.GetLayer() == lay and z.GetNetname() == NET and z.Outline().Contains(p)]
                    if not mine_z:
                        continue
                    pr = max(z.GetAssignedPriority() for z in mine_z)
                    if not any(z.GetLayer() == lay and z.GetNetname() != NET and z.GetAssignedPriority() > pr
                               and z.Outline().Contains(p) for z in zs):
                        plane_ok[i * g.ny + j] = 1
                        break

    # connectivity of the rail's existing copper (union-find on overlapping items)
    parent = list(range(len(items)))

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def cells_of(it):
        kind, layers, geom, _ = it
        out = set()
        if kind == "zone":
            bb = geom.GetBoundingBox()
            for i, j in g.cells_near(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())):
                x, y = g.xy(i, j)
                if geom.Outline().Contains(pcbnew.VECTOR2I(MM(x), MM(y))):
                    out.update((L, i, j) for L in layers)
        elif kind == "rect":   # grid points on the copper only, so a route never ends beside a pad
            x0, y0, x1, y1 = geom
            # inset: a bounding-box corner lies outside a rounded-rectangle pad, and a track ending there
            # does not connect (a pad too small for any grid point inside the inset keeps its full box)
            for e in (min(0.06, (x1 - x0) / 2, (y1 - y0) / 2), 0.0):
                for i, j in g.cells_near(*geom):
                    x, y = g.xy(i, j)
                    if x0 + e <= x <= x1 - e and y0 + e <= y <= y1 - e:
                        out.update((L, i, j) for L in layers)
                if out:
                    break
        elif kind == "circ":
            (cx, cy), r = geom
            for i, j in g.cells_near(cx - r, cy - r, cx + r, cy + r):
                x, y = g.xy(i, j)
                if math.hypot(x - cx, y - cy) <= r:
                    out.update((L, i, j) for L in layers)
        else:
            (a, b), w = geom
            for i, j in g.cells_near(min(a[0], b[0]) - w / 2, min(a[1], b[1]) - w / 2,
                                     max(a[0], b[0]) + w / 2, max(a[1], b[1]) + w / 2):
                x, y = g.xy(i, j)
                if seg_dist(x, y, a, b) <= w / 2:
                    out.update((L, i, j) for L in layers)
        return out
    cells = [cells_of(it) for it in items]
    owner = {}
    for k, cs in enumerate(cells):
        for c in cs:
            if c in owner:
                parent[find(k)] = find(owner[c])
            else:
                owner[c] = k
    groups = {}
    for k in range(len(items)):
        groups.setdefault(find(k), set()).update(cells[k])
    if plane:
        # pieces holding a via or a THT pad already reach the plane; the rest are routed to them,
        # or end in a new via where the plane is
        on_plane = {find(k) for k, it in enumerate(items) if it[3] == "via" or (it[0] == "rect" and set(it[1]) == set(ALL))}
        tree = set()
        for k in on_plane:
            tree |= groups.pop(k)
        if not quiet:
            print(f"{NET}: {len(groups)} piece(s) to join to the plane")
    else:
        root = find(next(k for k, it in enumerate(items) if it[3] == rail["root"]))
        tree = set(groups.pop(root))
        if not quiet:
            print(f"{NET}: {len(groups)} piece(s) to join to {rail['root']}")

    def neighbours(L, i, j):
        for di, dj, c in ((1, 0, 10), (-1, 0, 10), (0, 1, 10), (0, -1, 10), (1, 1, 14), (1, -1, 14), (-1, 1, 14), (-1, -1, 14)):
            ni, nj = i + di, j + dj
            if 0 <= ni < g.nx and 0 <= nj < g.ny:
                yield L, ni, nj, c
        if rail.get("via") and not via_bad[i * g.ny + j]:
            for L2 in LAYERS:
                if L2 != L:
                    yield L2, i, j, VIA_COST * 10

    def free(L, i, j):
        if L not in narrow:   # a via's cell on a layer this rail does not route
            return False
        k = i * g.ny + j
        return not narrow[L][k] or mine_n[L][k]

    def wide(c):
        k = c[1] * g.ny + c[2]
        return not blocked[c[0]][k] or mine_w[c[0]][k]

    # a coupled pair: cells at the pair pitch from the partner net's tracks cost 1, others HUG_COST
    hug = None
    if rail.get("hug"):
        hug = {L: bytearray(N) for L in LAYERS}
        for k in range(len(tracks)):
            t = tracks[k]
            L = next((n for n in LAYERS if t.GetLayer() == lid[n]), None)
            if t.GetClass() == "PCB_VIA" or L is None or t.GetNetname() != rail["hug"]:
                continue
            a = (mm(t.GetStart().x), mm(t.GetStart().y))
            b = (mm(t.GetEnd().x), mm(t.GetEnd().y))
            pitch = mm(t.GetWidth()) / 2 + cl(rail["hug"]) + WIDTH[L] / 2
            r = pitch + 1.5 * STEP
            for i, j in g.cells_near(min(a[0], b[0]) - r, min(a[1], b[1]) - r, max(a[0], b[0]) + r, max(a[1], b[1]) + r):
                x, y = g.xy(i, j)
                if seg_dist(x, y, a, b) <= r:
                    hug[L][i * g.ny + j] = 1

    added_tracks, added_vias, failed = 0, 0, []
    links = []
    while groups:
        # nearest piece to the tree first
        def gap(cs):
            # sorted: set order of the (layer, i, j) cells follows the per-process string hash
            sample = sorted(tree)[::max(1, len(tree) // 300)]
            return min(math.hypot(a[1] - b[1], a[2] - b[2]) for a in sorted(cs)[::max(1, len(cs) // 50)] for b in sample)
        key = min(groups, key=lambda k: gap(groups[k]))
        src = groups.pop(key)
        dist, prev, heap = {}, {}, []
        for c in src:
            if not free(*c):   # start only where a track centre fits
                continue
            dist[c] = 0
            heapq.heappush(heap, (0, c))
        goal, drop = None, False
        while heap:
            d, c = heapq.heappop(heap)
            if c[0].endswith("!"):   # a new via into the plane at this cell
                goal, drop = (c[0][:-1], c[1], c[2]), True
                break
            if d > dist.get(c, 1e18):
                continue
            if c in tree:
                goal = c
                break
            L, i, j = c
            if plane_ok is not None and plane_ok[i * g.ny + j]:
                heapq.heappush(heap, (d + VIA_COST * 10, (L + "!", i, j)))
            for L2, ni, nj, cost in neighbours(L, i, j):
                n = (L2, ni, nj)
                if not free(L2, ni, nj):
                    continue
                nd = d + (cost if wide(n) else cost * NECK_COST) * (LAYER_COST[L2] if L2 == L else 1)
                if hug is not None and not hug[L2][ni * g.ny + nj]:
                    nd += cost * (HUG_COST - 1)
                if nd < dist.get(n, 1e18):
                    dist[n] = nd
                    prev[n] = c
                    heapq.heappush(heap, (nd, n))
        name = next(it[3] for k, it in enumerate(items) if find(k) == key)
        if goal is None:
            failed.append(name)
            continue
        link = dict(cost=d, items=[])
        links.append(link)
        route = [goal]
        while route[-1] in prev:
            route.append(prev[route[-1]])
        route.reverse()   # from the tree back to the piece
        net = board.FindNet(NET)
        if drop:
            x, y = g.xy(goal[1], goal[2])
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
            v.SetWidth(MM(VIA[0]))
            v.SetDrill(MM(VIA[1]))
            v.SetNet(net)
            board.Add(v)
            link["items"].append(v)
            added_vias += 1
            _rast(None, "circ", ((x, y), VIA[1] / 2), VIA[1] / 2 + HOLE_CLR, via_bad)
            _rast(None, "circ", ((x, y), VIA[1] / 2), VIA[1] / 2 + HOLE_CLR, plane_ok)
        # split the route into straight single-layer runs of one width class; a layer change is a via
        runs, run, cls = [], [route[0]], None
        for c in route[1:]:
            p = run[-1]
            if c[0] != p[0]:
                runs.append((run, cls))
                runs.append(("via", c))
                run, cls = [c], None
                continue
            step_cls = wide(p) and wide(c)
            d = (c[1] - p[1], c[2] - p[2])
            if len(run) >= 2 and (step_cls != cls or d != (p[1] - run[-2][1], p[2] - run[-2][2])):
                runs.append((run, cls))
                run = [p]
            run.append(c)
            cls = step_cls
        runs.append((run, cls))
        for r, c in runs:
            if r == "via":
                x, y = g.xy(c[1], c[2])
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
                v.SetWidth(MM(VIA[0]))
                v.SetDrill(MM(VIA[1]))
                v.SetNet(net)
                board.Add(v)
                link["items"].append(v)
                added_vias += 1
            elif len(r) >= 2:
                (L, i0, j0), (_, i1, j1) = r[0], r[-1]
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(pcbnew.VECTOR2I(MM(g.xy(i0, j0)[0]), MM(g.xy(i0, j0)[1])))
                t.SetEnd(pcbnew.VECTOR2I(MM(g.xy(i1, j1)[0]), MM(g.xy(i1, j1)[1])))
                t.SetWidth(MM(WIDTH[L] if c else NECK))
                t.SetLayer(lid[L])
                t.SetNet(net)
                board.Add(t)
                link["items"].append(t)
                added_tracks += 1
        for a, b in zip(route, route[1:]):   # the new copper: its centreline at the width drawn
            for c in (a, b):
                tree.add(c)
                mine_n[c[0]][c[1] * g.ny + c[2]] = 1
                if wide(a) and wide(b):
                    mine_w[c[0]][c[1] * g.ny + c[2]] = 1
        tree.update(src)
    if not quiet:
        print(f"{NET}: {added_tracks} tracks, {added_vias} vias; not reached: {' '.join(failed) or 'none'}")
    return links, failed


def snapshot(item):
    """Geometry of a routed track or via, to put it back after a trial rip-up."""
    if item.GetClass() == "PCB_VIA":
        v = pcbnew.Cast_to_PCB_VIA(item)
        return ("via", pcbnew.VECTOR2I(v.GetPosition()), v.GetWidth(pcbnew.F_Cu), v.GetDrillValue(), v.GetNetCode())
    return ("track", pcbnew.VECTOR2I(item.GetStart()), pcbnew.VECTOR2I(item.GetEnd()), item.GetWidth(), item.GetLayer(), item.GetNetCode())


def restore(board, snap):
    if snap[0] == "via":
        _, pos, w, drill, net = snap
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pos)
        v.SetWidth(w)
        v.SetDrill(drill)
        v.SetNetCode(net)
    else:
        _, a, b, w, layer, net = snap
        v = pcbnew.PCB_TRACK(board)
        v.SetStart(a)
        v.SetEnd(b)
        v.SetWidth(w)
        v.SetLayer(layer)
        v.SetNetCode(net)
    board.Add(v)
    return v


def refine(board, rail, links):
    """Rip-up and reroute: links are added nearest piece first, so an early link can take a long way
    round to copper that a later link brings close (a +5V run on B.Cu to the core buck's PG pull-up
    while the L3 run passed 1 mm away). Take each link out, most expensive first, and reroute the
    pieces it joined against the finished tree; keep the reroute only if it costs less. A link whose
    pieces stay joined without it is dropped."""
    better = 0
    for link in sorted(links, key=lambda l: -l["cost"]):
        snaps = [snapshot(it) for it in link["items"]]
        for it in link["items"]:
            board.Remove(it)
        new, failed = route(board, rail, quiet=True)
        cost = sum(n["cost"] for n in new)
        if not failed and cost < link["cost"] - 1e-6:
            better += 1
            link["items"] = [it for n in new for it in n["items"]]
            link["cost"] = cost
            continue
        for n in new:
            for it in n["items"]:
                board.Remove(it)
        link["items"] = [restore(board, sn) for sn in snaps]
    print(f"{rail['net']}: refine replaced {better} of {len(links)} link(s)")


def main(path):
    board = pcbnew.LoadBoard(path)
    for rail in RAILS:
        links, _ = route(board, rail)
        if not rail.get("plane") and rail.get("refine", True):
            refine(board, rail, links)
    board.Save(path)


if __name__ == "__main__":
    main(sys.argv[1])
