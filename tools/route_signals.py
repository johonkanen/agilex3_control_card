"""Signal routing, first pass: every signal net whose pads are all on the top (or through-hole) is
routed on F.Cu without vias, shortest nets first.

    squashfs-root/AppRun python3.11 -I tools/route_signals.py hardware/control_card.kicad_pcb

Grid router: a 0.025 mm grid (the FPGA balls sit on mixed pitches down to 0.65 mm, where a 0.1 mm
track between two balls has a 0.026 mm window for its centre, so no coarser grid lines up with every
channel), A* with 8 directions and a turn penalty so paths come out as straight 45/90 degree runs.
Each net is routed inside a window around its pads (whole board if that fails), with the obstacle
geometry read once and updated after each net.
Clearances: net class (0.15 mm to switch nodes, else 0.1 mm) plus a grid margin, 0.2 mm from
drill holes, 0.3 mm from the board edge; no track between the pads of a 2-pad part.
Prints the nets it could not route; DRC (build_pcb.sh) checks the result.
"""
import heapq
import math
import os
import sys
import time
from collections import defaultdict

import pcbnew

MM = pcbnew.FromMM
BOARD = (75.2, 94.9, 107.738, 128.7)
STEP = 0.025
MARGIN = 0.012            # grid slack: a diagonal step between checked cells
EDGE = 0.3
HOLE_CLR = 0.2
PTH_CLR = 0.28            # through-hole pad (connector pin) hole edge to other copper: JLCPCB multilayer minimum
WIDTH = 0.1               # Default net class track
WINDOW = (3.0, 8.0)       # routing window margins around a net's pads: first try, retry
NEGOTIATE = 6             # negotiation rounds (the overlap count settles by then)
HIST_INC = 0.5            # history cost added per round to cells of overlapping routes
DETOUR = (1.5, 3.0)       # a connection may cost at most 1.5x its straight-line bound + 3 mm; longer
                          # detours wall off later nets, so those wait for the via pass instead
TURN = {0: 0, 1: 4, 2: 12, 3: 40}   # extra cost (grid steps) per 45-degree turn count
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
POWER = ("GND", "VCC_SENSE_N", "VCC_SENSE_P")


def is_signal(net):
    return net and not net.startswith(("+", "/Power/", "unconnected")) and net not in POWER


def clr(net):
    return (0.15 if net.startswith("/Power/SW") else 0.1) + MARGIN


def mm(v):
    return pcbnew.ToMM(v)


def seg_dist(px, py, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / L))
    return math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy))


class Item:
    """F.Cu copper (or a drill hole) as a shape: rect (x0, y0, x1, y1), circ ((cx, cy), r) or
    seg ((a, b), w); hole = drill radius for holes; name for pads."""
    __slots__ = ("kind", "geom", "net", "hole", "name", "bb")

    def __init__(self, kind, geom, net, hole=0.0, name=""):
        self.kind, self.geom, self.net, self.hole, self.name = kind, geom, net, hole, name
        if kind == "rect":
            self.bb = geom
        elif kind == "circ":
            (cx, cy), r = geom
            self.bb = (cx - r, cy - r, cx + r, cy + r)
        else:
            (a, b), w = geom
            self.bb = (min(a[0], b[0]) - w / 2, min(a[1], b[1]) - w / 2, max(a[0], b[0]) + w / 2, max(a[1], b[1]) + w / 2)

    def dist(self, x, y):
        """Distance from (x, y) to the copper (0 inside)."""
        if self.kind == "rect":
            x0, y0, x1, y1 = self.geom
            return math.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1))
        if self.kind == "circ":
            (cx, cy), r = self.geom
            return max(0.0, math.hypot(x - cx, y - cy) - r)
        (a, b), w = self.geom
        return max(0.0, seg_dist(x, y, a, b) - w / 2)


def collect(board):
    fl = board.GetLayerID("F.Cu")
    items, gaps = [], []
    for fp in board.GetFootprints():
        pads = [p for p in fp.Pads() if p.GetNumber()]
        for pad in pads:
            tht = pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
            if not (tht or pad.IsOnLayer(fl)):
                continue
            c = (mm(pad.GetPosition().x), mm(pad.GetPosition().y))
            name = f"{fp.GetReference()}.{pad.GetNumber()}"
            if pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE:
                it = Item("circ", (c, mm(pad.GetSize().x) / 2), pad.GetNetname(), name=name)
            else:
                b = pad.GetBoundingBox()
                it = Item("rect", (mm(b.GetLeft()), mm(b.GetTop()), mm(b.GetRight()), mm(b.GetBottom())), pad.GetNetname(), name=name)
            items.append(it)
            if tht:
                items.append(Item("circ", (c, mm(pad.GetDrillSize().x) / 2), pad.GetNetname(), hole=2))   # 2: plated pin hole
        if len(pads) == 2 and all(p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and p.IsOnLayer(fl) for p in pads):
            # no track under a passive's body, between its pads
            bs = [p.GetBoundingBox() for p in pads]
            L = [mm(b.GetLeft()) for b in bs]
            R = [mm(b.GetRight()) for b in bs]
            T = [mm(b.GetTop()) for b in bs]
            B = [mm(b.GetBottom()) for b in bs]
            if max(L) > min(R):
                gaps.append(Item("rect", (min(R), min(T), max(L), max(B)), "~gap"))
            elif max(T) > min(B):
                gaps.append(Item("rect", (min(L), min(B), max(R), max(T)), "~gap"))
    tracks = board.Tracks()
    for k in range(len(tracks)):
        t = tracks[k]
        if t.GetClass() == "PCB_VIA":
            v = pcbnew.Cast_to_PCB_VIA(t)
            c = (mm(v.GetPosition().x), mm(v.GetPosition().y))
            items.append(Item("circ", (c, mm(v.GetWidth(fl)) / 2), v.GetNetname(), name="via"))
            items.append(Item("circ", (c, mm(v.GetDrillValue()) / 2), v.GetNetname(), hole=1))
        elif t.GetLayer() == fl:
            a = (mm(t.GetStart().x), mm(t.GetStart().y))
            b = (mm(t.GetEnd().x), mm(t.GetEnd().y))
            items.append(Item("seg", ((a, b), mm(t.GetWidth())), t.GetNetname(), name="track"))
    return items, gaps


class Index:
    def __init__(self, items, cell=1.0):
        self.cell = cell
        self.grid = defaultdict(list)
        for it in items:
            self.add(it)

    def add(self, it):
        c = self.cell
        for i in range(int(it.bb[0] // c), int(it.bb[2] // c) + 1):
            for j in range(int(it.bb[1] // c), int(it.bb[3] // c) + 1):
                self.grid[(i, j)].append(it)

    def query(self, x0, y0, x1, y1):
        c, seen = self.cell, set()
        for i in range(int(x0 // c), int(x1 // c) + 1):
            for j in range(int(y0 // c), int(y1 // c) + 1):
                for it in self.grid.get((i, j), ()):
                    if id(it) not in seen:
                        seen.add(id(it))
                        yield it


def route_net(net, idxs, win, soft=None, hist=None, pres=0.0):
    """Route one net inside window win = (x0, y0, x1, y1) around the copper in the given indexes.
    soft: an index of other signal nets' tracks that may be crossed at a cost (pres per net per
    step), plus the history cost hist[(world i, world j)] (negotiated routing).
    Returns the new track segments ((x, y), (x, y)) and the names of pieces not reached."""
    x0, y0 = math.floor(max(win[0], BOARD[0]) / STEP) * STEP, math.floor(max(win[1], BOARD[1]) / STEP) * STEP
    x1, y1 = min(win[2], BOARD[2]), min(win[3], BOARD[3])
    nx, ny = int((x1 - x0) / STEP) + 1, int((y1 - y0) / STEP) + 1
    xy = lambda i, j: (x0 + i * STEP, y0 + j * STEP)   # noqa: E731
    blocked = bytearray(nx * ny)
    softc = bytearray(nx * ny)  # other signal nets whose keep-out covers the cell
    hist = hist or {}
    wi0, wj0 = round(x0 / STEP), round(y0 / STEP)
    mine = bytearray(nx * ny)   # track centre inside own copper (eroded by half the width)
    own = []

    def cells(bb, r):
        i0, j0 = max(0, int((bb[0] - r - x0) / STEP)), max(0, int((bb[1] - r - y0) / STEP))
        i1, j1 = min(nx - 1, int((bb[2] + r - x0) / STEP) + 1), min(ny - 1, int((bb[3] + r - y0) / STEP) + 1)
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                yield i, j

    edge = EDGE + WIDTH / 2
    for i in range(nx):
        for j in range(ny):
            x, y = xy(i, j)
            if x < BOARD[0] + edge or x > BOARD[2] - edge or y < BOARD[1] + edge or y > BOARD[3] - edge:
                blocked[i * ny + j] = 1
    for it in (it for idx in idxs for it in idx.query(x0 - 1, y0 - 1, x1 + 1, y1 + 1)):
        if it.net == net and not it.hole:
            own.append(it)
            for i, j in cells(it.bb, 0):
                if inside(it, *xy(i, j)):
                    mine[i * ny + j] = 1
            continue
        if it.net == net and it.hole:
            continue
        need = WIDTH / 2 + ((PTH_CLR if it.hole == 2 else HOLE_CLR) + MARGIN if it.hole else clr(it.net) if it.net != "~gap" else 0)
        for i, j in cells(it.bb, need):
            k = i * ny + j
            if not blocked[k]:
                x, y = xy(i, j)
                if it.dist(x, y) < need:
                    blocked[k] = 1
    if soft is not None:
        for it in soft.query(x0 - 1, y0 - 1, x1 + 1, y1 + 1):
            if it.net == net:
                continue
            need = WIDTH / 2 + clr(it.net)
            for i, j in cells(it.bb, need):
                k = i * ny + j
                if softc[k] < 255 and it.dist(*xy(i, j)) < need:
                    softc[k] += 1
    # pieces of this net (union-find over overlapping own items)
    parent = list(range(len(own)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a in range(len(own)):
        for b in range(a + 1, len(own)):
            A, B = own[a], own[b]
            if A.bb[0] <= B.bb[2] and B.bb[0] <= A.bb[2] and A.bb[1] <= B.bb[3] and B.bb[1] <= A.bb[3]:
                # overlap test on a few points of B against A
                if any(A.dist(x, y) == 0 for x, y in sample(B)):
                    parent[find(a)] = find(b)
    groups = defaultdict(list)
    for a, it in enumerate(own):
        groups[find(a)].append(it)
    pieces = []
    for g in groups.values():
        cs = set()
        for it in g:
            for i, j in cells(it.bb, 0):
                if mine[i * ny + j] and inside(it, *xy(i, j)):
                    cs.add((i, j))
        name = next((it.name for it in g if it.name not in ("track", "via")), "track")
        pieces.append((name, cs))
    pieces = [p for p in pieces if p[1]]
    if len(pieces) < 2:
        return [], []
    pieces.sort(key=lambda p: p[0])
    tree = set(pieces[0][1])
    todo = pieces[1:]
    paths, failed = [], []

    def free(i, j):
        k = i * ny + j
        return not blocked[k] or mine[k]

    while todo:
        # nearest piece to the tree
        tl = sorted(tree)[::max(1, len(tree) // 200)]
        todo.sort(key=lambda p: min(math.hypot(a[0] - b[0], a[1] - b[1]) for a in sorted(p[1])[::max(1, len(p[1]) // 30)] for b in tl))
        name, src = todo.pop(0)
        tb = (min(c[0] for c in tree), min(c[1] for c in tree), max(c[0] for c in tree), max(c[1] for c in tree))

        def h(i, j):   # octile distance to the tree's bounding box (admissible)
            dx = max(tb[0] - i, 0, i - tb[2])
            dy = max(tb[1] - j, 0, j - tb[3])
            return 10 * max(dx, dy) + 4 * min(dx, dy)
        heap, dist, prev = [], {}, {}
        for (i, j) in src:
            if free(i, j):
                s = (i, j, 8)
                dist[s] = 0
                heapq.heappush(heap, (h(i, j), 0, 0, s))
        # the detour limit is on path length only, not on the congestion costs
        limit = DETOUR[0] * min((f for f, _, _, _ in heap), default=0) + DETOUR[1] / STEP * 10
        goal = None
        while heap:
            f, d, gl, s = heapq.heappop(heap)
            if d > dist.get(s, 1e18):
                continue
            if gl + h(s[0], s[1]) > limit:
                continue
            i, j, dr = s
            if (i, j) in tree:
                goal = s
                break
            for nd_, (di, dj) in enumerate(DIRS):
                ni, nj = i + di, j + dj
                if not (0 <= ni < nx and 0 <= nj < ny) or not free(ni, nj):
                    continue
                if di and dj and not (free(i + di, j) or free(i, j + dj)):
                    continue   # no squeezing diagonally between two blocked cells
                step = 14 if di and dj else 10
                turn = 0 if dr == 8 else TURN[min((nd_ - dr) % 8, (dr - nd_) % 8)] if min((nd_ - dr) % 8, (dr - nd_) % 8) < 4 else 999
                n = (ni, nj, nd_)
                k = ni * ny + nj
                nd = d + step + turn
                if softc[k] and not mine[k]:
                    nd += step * pres * softc[k]
                hc = hist.get((wi0 + ni, wj0 + nj))
                if hc:
                    nd += step * hc
                if nd < dist.get(n, 1e18):
                    dist[n] = nd
                    prev[n] = s
                    heapq.heappush(heap, (nd + h(ni, nj), nd, gl + step, n))
        if goal is None:
            failed.append(name)
            continue
        path = [goal]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        path = [(i, j) for i, j, _ in path]
        paths.append(path)
        for c in path:
            tree.add(c)
            mine[c[0] * ny + c[1]] = 1
        tree |= src
    segs = [(xy(*a), xy(*b)) for p in paths for a, b in straight_runs(p) if a != b]
    return segs, failed


def inside(it, x, y):
    """True if a WIDTH track centred at (x, y) stays on the item's copper (the copper eroded by half
    the width; an item narrower than the track keeps a sliver along its middle)."""
    e = WIDTH / 2
    if it.kind == "rect":
        x0, y0, x1, y1 = it.geom
        ex, ey = min(e, (x1 - x0) / 2 - STEP), min(e, (y1 - y0) / 2 - STEP)
        return x0 + ex <= x <= x1 - ex and y0 + ey <= y <= y1 - ey
    if it.kind == "circ":
        (cx, cy), r = it.geom
        return math.hypot(x - cx, y - cy) <= max(r - e, STEP)
    (a, b), w = it.geom
    return seg_dist(x, y, a, b) <= max(w / 2 - e, STEP)


def sample(it):
    if it.kind == "rect":
        x0, y0, x1, y1 = it.geom
        return [(x0, y0), (x1, y0), (x0, y1), (x1, y1), ((x0 + x1) / 2, (y0 + y1) / 2)]
    if it.kind == "circ":
        (cx, cy), r = it.geom
        return [(cx, cy)] + [(cx + r * math.cos(a), cy + r * math.sin(a)) for a in (0, 1.57, 3.14, 4.71)]
    (a, b), w = it.geom
    return [a, b, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)]


def straight_runs(path):
    """Cell path -> list of (start, end) cells of straight runs."""
    runs, start = [], 0
    for k in range(1, len(path) - 1):
        d0 = (path[k][0] - path[k - 1][0], path[k][1] - path[k - 1][1])
        d1 = (path[k + 1][0] - path[k][0], path[k + 1][1] - path[k][1])
        if d0 != d1:
            runs.append((path[start], path[k]))
            start = k
    if len(path) >= 2:
        runs.append((path[start], path[-1]))
    return runs


def seg_seg_dist(a, b, c, d):
    if segs_cross(a, b, c, d):
        return 0.0
    return min(seg_dist(a[0], a[1], c, d), seg_dist(b[0], b[1], c, d), seg_dist(c[0], c[1], a, b), seg_dist(d[0], d[1], a, b))


def segs_cross(a, b, c, d):
    o = lambda p, q, r: (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])   # noqa: E731
    return o(a, b, c) * o(a, b, d) < 0 and o(c, d, a) * o(c, d, b) < 0


class Router:
    """Signal routes kept in memory (net -> segments) so they can be ripped up; written at the end."""
    def __init__(self, base):
        self.base = base
        self.routes = {}
        self.sig = Index([])

    def rebuild(self):
        self.sig = Index([Item("seg", (sg, WIDTH), n, name="track") for n, ss in self.routes.items() for sg in ss])

    def attempt(self, net, pts, ignore_signals=False, hist=None, pres=None):
        """pres None: other signals block; a number: they may be crossed at that cost (negotiation)."""
        idxs = [self.base] if ignore_signals or pres is not None else [self.base, self.sig]
        soft = self.sig if pres is not None else None
        for m in WINDOW:
            win = (min(p[0] for p in pts) - m, min(p[1] for p in pts) - m, max(p[0] for p in pts) + m, max(p[1] for p in pts) + m)
            segs, miss = route_net(net, idxs, win, soft, hist, pres or 0.0)
            if not miss:
                return segs
        return None

    def put(self, net, segs):
        self.routes[net] = segs
        for sg in segs:
            self.sig.add(Item("seg", (sg, WIDTH), net, name="track"))

    def blockers(self, net, segs):
        out = set()
        for a, b in segs:
            bb = (min(a[0], b[0]) - 0.5, min(a[1], b[1]) - 0.5, max(a[0], b[0]) + 0.5, max(a[1], b[1]) + 0.5)
            for it in self.sig.query(*bb):
                # the real clearance (the router's grid margin is slack for its diagonal steps)
                if it.net != net and seg_seg_dist(a, b, *it.geom[0]) < WIDTH + clr(it.net) - MARGIN + 0.001:
                    out.add(it.net)
        return out


def main(path):
    board = pcbnew.LoadBoard(path)
    fl = board.GetLayerID("F.Cu")
    items, gaps = collect(board)
    nets = defaultdict(list)
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNumber() and is_signal(p.GetNetname()):
                nets[p.GetNetname()].append(p)
    todo = []
    for net, pads in nets.items():
        if len(pads) < 2 or not all(p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH or p.IsOnLayer(fl) for p in pads):
            continue
        pts = [(mm(p.GetPosition().x), mm(p.GetPosition().y)) for p in pads]
        done, rest, L = [pts[0]], pts[1:], 0.0
        while rest:   # MST length, for the order
            d, k = min((min(math.hypot(a[0] - r[0], a[1] - r[1]) for a in done), k) for k, r in enumerate(rest))
            L += d
            done.append(rest.pop(k))
        todo.append((L, net, pts))
    todo.sort()
    if os.environ.get("ROUTE_ONLY"):   # re-route just these nets on a hand-edited board (comma separated)
        only = set(os.environ["ROUTE_ONLY"].split(","))
        todo = [t for t in todo if t[1] in only]
    pts_of = {net: pts for _, net, pts in todo}
    length = {net: L for L, net, _ in todo}
    r = Router(Index(items + gaps))
    # negotiated congestion routing (PathFinder): every net is routed with the other signal nets'
    # copper as a cost instead of an obstacle; cells where nets still overlap get a growing history
    # cost and the present-sharing cost rises each round, until no two nets overlap
    t0 = time.time()
    hist = defaultdict(float)
    unroutable = []
    conflicted = [net for _, net, _ in todo]
    for rnd in range(NEGOTIATE):
        pres = 0.5 * 1.7 ** rnd
        for _, net, _ in todo:
            if net not in conflicted or net in unroutable:
                continue
            r.routes.pop(net, None)
            r.rebuild()
            segs = r.attempt(net, pts_of[net], hist=hist, pres=pres)
            if segs is None:
                unroutable.append(net)   # not even across other signals (power copper, detour limit)
            else:
                r.put(net, segs)
        conflicted = set()
        for net, segs in r.routes.items():
            blk = r.blockers(net, segs)
            if blk:
                conflicted |= blk | {net}
        for net in conflicted:   # history on the cells of overlapping routes
            for a, b in r.routes[net]:
                n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / STEP))
                for k in range(n + 1):
                    hist[(round((a[0] + (b[0] - a[0]) * k / n) / STEP), round((a[1] + (b[1] - a[1]) * k / n) / STEP))] += HIST_INC
        print(f"round {rnd + 1}: {len(r.routes)} routed, {len(conflicted)} overlapping ({time.time() - t0:.0f} s)", flush=True)
        if not conflicted:
            break
    # still overlapping: drop nets (most conflicts first, then longest) until the rest are legal
    while True:
        cnt = {net: len(r.blockers(net, segs)) for net, segs in r.routes.items()}
        bad = [n for n, c in cnt.items() if c]
        if not bad:
            break
        drop = max(bad, key=lambda n: (cnt[n], length[n]))
        r.routes.pop(drop)
        r.rebuild()
    # the dropped nets get one more try with every other route as an obstacle: the routes they
    # crossed may have moved since
    for _, net, pts in todo:
        if net not in r.routes and net not in unroutable:
            segs = r.attempt(net, pts)
            if segs is not None:
                r.put(net, segs)
    # rip-up: a net still failing that routes on its own takes its path; the nets in that path are
    # ripped up and rerouted after it, and the change is kept only if they all route again (e.g. a
    # ball whose only exit an earlier, tighter route closed)
    for _, net, pts in todo:
        if net in r.routes or net in unroutable:
            continue
        free = r.attempt(net, pts, ignore_signals=True)
        if free is None:
            continue
        blk = r.blockers(net, free)
        saved = {b: r.routes.pop(b) for b in blk}
        r.rebuild()
        segs = r.attempt(net, pts)
        ok = segs is not None
        if ok:
            r.put(net, segs)
            for b in sorted(blk, key=lambda n: length[n]):
                s2 = r.attempt(b, pts_of[b])
                if s2 is None:
                    ok = False
                    break
                r.put(b, s2)
        if not ok:   # restore
            for b in blk:
                r.routes.pop(b, None)
            r.routes.pop(net, None)
            r.routes.update(saved)
            r.rebuild()
        else:
            print(f"  rip-up: {net} routed, {len(blk)} net(s) moved", flush=True)
    failed = [net for _, net, _ in todo if net not in r.routes]
    for net, segs in sorted(r.routes.items()):
        ni = board.FindNet(net)
        for A, B in segs:
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(pcbnew.VECTOR2I(MM(A[0]), MM(A[1])))
            t.SetEnd(pcbnew.VECTOR2I(MM(B[0]), MM(B[1])))
            t.SetWidth(MM(WIDTH))
            t.SetLayer(fl)
            t.SetNet(ni)
            board.Add(t)
    board.Save(path)
    print(f"top-only signal nets: {len(r.routes)} of {len(todo)} routed on F.Cu without vias")
    if failed:
        print(f"not routed ({len(failed)}): " + " ".join(sorted(failed)))


if __name__ == "__main__":
    main(sys.argv[1])
