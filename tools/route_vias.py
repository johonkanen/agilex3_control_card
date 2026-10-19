"""Signal routing, second pass: every signal net still open after tools/route_signals.py is routed
on F.Cu and B.Cu with vias.

    squashfs-root/AppRun python3.11 -I tools/route_vias.py hardware/control_card.kicad_pcb

The same grid router as the first pass (0.025 mm grid, A* with a turn penalty, detour limit,
negotiated congestion, a retry and a rip-up pass), on two layers: a step to the other layer places
a via (0.3/0.15 mm) and costs as much as VIA_COST of track. All copper already on the board is a
fixed obstacle, the first pass's tracks included. A via keeps clear of other nets' copper on every
layer (inner-layer tracks such as the 5 V run on L3 included; the planes clear themselves), 0.2 mm
from other drill holes, and is not placed between a passive's pads. L3 is not used for signals:
it is mostly the +1V8/+1V2 pour.
"""
import heapq
import math
import os
import sys
import time
from collections import defaultdict

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from route_signals import (BOARD, DETOUR, DIRS, EDGE, HIST_INC, HOLE_CLR, PTH_CLR, MARGIN, MM, STEP, TURN,  # noqa: E402
                           WIDTH, WINDOW, Item, clr, inside, is_signal, mm, sample, seg_dist,
                           seg_seg_dist)

LAYERS = ("F", "B")          # routing layers
VIA = (0.3, 0.15)            # signal via pad, drill
VIA_COST = 1.5               # mm of track a layer change is worth
# a via's copper keeps the net-class clearance and its hole HOLE_CLR from other copper; with the
# 0.3/0.15 mm via the hole clearance is the stricter one (0.125 mm copper to copper)
VIA_GAP = HOLE_CLR - (VIA[0] - VIA[1]) / 2
NEGOTIATE = 4                # negotiation rounds


class LItem(Item):
    """An Item on a set of layers: "F", "B", "I" (any inner layer); holes are on all."""
    __slots__ = ("layers",)

    def __init__(self, kind, geom, net, layers, hole=0.0, name=""):
        super().__init__(kind, geom, net, hole, name)
        self.layers = frozenset(layers)


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


def collect(board):
    fl, bl = board.GetLayerID("F.Cu"), board.GetLayerID("B.Cu")
    lname = lambda lid: "F" if lid == fl else "B" if lid == bl else "I"   # noqa: E731
    items = []
    for fp in board.GetFootprints():
        pads = [p for p in fp.Pads() if p.GetNumber()]
        for pad in pads:
            tht = pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
            layers = {"F", "B", "I"} if tht else {L for L, lid in (("F", fl), ("B", bl)) if pad.IsOnLayer(lid)}
            c = (mm(pad.GetPosition().x), mm(pad.GetPosition().y))
            name = f"{fp.GetReference()}.{pad.GetNumber()}"
            if pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE:
                items.append(LItem("circ", (c, mm(pad.GetSize().x) / 2), pad.GetNetname(), layers, name=name))
            else:
                b = pad.GetBoundingBox()
                items.append(LItem("rect", (mm(b.GetLeft()), mm(b.GetTop()), mm(b.GetRight()), mm(b.GetBottom())),
                                   pad.GetNetname(), layers, name=name))
            if tht:
                items.append(LItem("circ", (c, mm(pad.GetDrillSize().x) / 2), pad.GetNetname(), (), hole=2))   # 2: plated pin hole
        if len(pads) == 2 and all(p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD for p in pads):
            # no track or via under a passive's body, between its pads
            side = "F" if pads[0].IsOnLayer(fl) else "B"
            bs = [p.GetBoundingBox() for p in pads]
            L = [mm(b.GetLeft()) for b in bs]
            R = [mm(b.GetRight()) for b in bs]
            T = [mm(b.GetTop()) for b in bs]
            B = [mm(b.GetBottom()) for b in bs]
            if max(L) > min(R):
                items.append(LItem("rect", (min(R), min(T), max(L), max(B)), "~gap", {side}))
            elif max(T) > min(B):
                items.append(LItem("rect", (min(L), min(B), max(R), max(T)), "~gap", {side}))
    tracks = board.Tracks()
    for k in range(len(tracks)):
        t = tracks[k]
        if t.GetClass() == "PCB_VIA":
            v = pcbnew.Cast_to_PCB_VIA(t)
            c = (mm(v.GetPosition().x), mm(v.GetPosition().y))
            items.append(LItem("circ", (c, mm(v.GetWidth(fl)) / 2), v.GetNetname(), {"F", "B", "I"}, name="via"))
            items.append(LItem("circ", (c, mm(v.GetDrillValue()) / 2), v.GetNetname(), (), hole=1))
        else:
            a = (mm(t.GetStart().x), mm(t.GetStart().y))
            b = (mm(t.GetEnd().x), mm(t.GetEnd().y))
            items.append(LItem("seg", ((a, b), mm(t.GetWidth())), t.GetNetname(), {lname(t.GetLayer())}, name="track"))
    return items


def route_net(net, idxs, win, soft=None, hist=None, pres=0.0):
    """Route one net on LAYERS inside window win. Returns ([(layer, A, B)], [via xy], missing pieces)."""
    x0, y0 = math.floor(max(win[0], BOARD[0]) / STEP) * STEP, math.floor(max(win[1], BOARD[1]) / STEP) * STEP
    x1, y1 = min(win[2], BOARD[2]), min(win[3], BOARD[3])
    nx, ny = int((x1 - x0) / STEP) + 1, int((y1 - y0) / STEP) + 1
    N = nx * ny
    xy = lambda i, j: (x0 + i * STEP, y0 + j * STEP)   # noqa: E731
    nl = len(LAYERS)
    blocked = [bytearray(N) for _ in LAYERS]
    mine = [bytearray(N) for _ in LAYERS]
    softc = [bytearray(N) for _ in LAYERS]
    via_bad = bytearray(N)
    softv = bytearray(N)         # other signal nets a via here would come too close to
    hist = hist or {}
    wi0, wj0 = round(x0 / STEP), round(y0 / STEP)
    vr = VIA[0] / 2
    own = []

    def cells(bb, r):
        i0, j0 = max(0, int((bb[0] - r - x0) / STEP)), max(0, int((bb[1] - r - y0) / STEP))
        i1, j1 = min(nx - 1, int((bb[2] + r - x0) / STEP) + 1), min(ny - 1, int((bb[3] + r - y0) / STEP) + 1)
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                yield i, j

    def mark(arr, it, need):
        for i, j in cells(it.bb, need):
            k = i * ny + j
            if not arr[k] and it.dist(*xy(i, j)) < need:
                arr[k] = 1

    for i in range(nx):
        for j in range(ny):
            x, y = xy(i, j)
            k = i * ny + j
            e = min(x - BOARD[0], BOARD[2] - x, y - BOARD[1], BOARD[3] - y)
            if e < EDGE + WIDTH / 2:
                for L in range(nl):
                    blocked[L][k] = 1
            if e < EDGE + vr:
                via_bad[k] = 1
    for it in (it for idx in idxs for it in idx.query(x0 - 1, y0 - 1, x1 + 1, y1 + 1)):
        if it.hole:
            hc = PTH_CLR if it.hole == 2 else HOLE_CLR
            if it.net != net:
                for L in range(nl):
                    mark(blocked[L], it, WIDTH / 2 + hc + MARGIN)
            mark(via_bad, it, vr + hc + MARGIN)   # copper to hole, and hole to hole
            continue
        if it.net == net:
            own.append(it)
            if it.name.startswith("U1."):   # no via in an FPGA signal ball (they escape on L1)
                mark(via_bad, it, vr + clr(net))
            for L, ln in enumerate(LAYERS):
                if ln in it.layers:
                    for i, j in cells(it.bb, 0):
                        if inside(it, *xy(i, j)):
                            mine[L][i * ny + j] = 1
            continue
        gap = it.net == "~gap"
        c = 0.0 if gap else clr(it.net)
        for L, ln in enumerate(LAYERS):
            if ln in it.layers:
                mark(blocked[L], it, WIDTH / 2 + c)
        mark(via_bad, it, vr + (0.0 if gap else max(c, VIA_GAP + MARGIN)))
    if soft is not None:
        for it in soft.query(x0 - 1, y0 - 1, x1 + 1, y1 + 1):
            if it.net == net or it.hole:
                continue
            need = WIDTH / 2 + clr(it.net)
            for L, ln in enumerate(LAYERS):
                if ln in it.layers:
                    for i, j in cells(it.bb, need):
                        k = i * ny + j
                        if softc[L][k] < 255 and it.dist(*xy(i, j)) < need:
                            softc[L][k] += 1
            vneed = vr + max(clr(it.net), VIA_GAP + MARGIN)
            for i, j in cells(it.bb, vneed):
                k = i * ny + j
                if softv[k] < 255 and it.dist(*xy(i, j)) < vneed:
                    softv[k] += 1
    # pieces: own copper joined where items overlap on a common layer
    parent = list(range(len(own)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a in range(len(own)):
        for b in range(a + 1, len(own)):
            A, B = own[a], own[b]
            if A.layers & B.layers and A.bb[0] <= B.bb[2] and B.bb[0] <= A.bb[2] and A.bb[1] <= B.bb[3] and B.bb[1] <= A.bb[3]:
                if any(A.dist(x, y) == 0 for x, y in sample(B)):
                    parent[find(a)] = find(b)
    groups = defaultdict(list)
    for a, it in enumerate(own):
        groups[find(a)].append(it)
    pieces = []
    for g in groups.values():
        cs = set()
        for it in g:
            for L, ln in enumerate(LAYERS):
                if ln in it.layers:
                    for i, j in cells(it.bb, 0):
                        if mine[L][i * ny + j] and inside(it, *xy(i, j)):
                            cs.add((L, i, j))
        name = next((it.name for it in g if it.name not in ("track", "via")), "track")
        pieces.append((name, cs))
    pieces = [p for p in pieces if p[1]]
    if len(pieces) < 2:
        return [], [], []
    pieces.sort(key=lambda p: p[0])
    tree = set(pieces[0][1])
    todo = pieces[1:]
    paths, failed = [], []

    def free(L, i, j):
        k = i * ny + j
        return not blocked[L][k] or mine[L][k]

    vcost = int(VIA_COST / STEP * 10)
    while todo:
        tl = sorted(tree)[::max(1, len(tree) // 200)]
        todo.sort(key=lambda p: min(math.hypot(a[1] - b[1], a[2] - b[2]) for a in sorted(p[1])[::max(1, len(p[1]) // 30)] for b in tl))
        name, src = todo.pop(0)
        tb = (min(c[1] for c in tree), min(c[2] for c in tree), max(c[1] for c in tree), max(c[2] for c in tree))

        def h(i, j):
            dx = max(tb[0] - i, 0, i - tb[2])
            dy = max(tb[1] - j, 0, j - tb[3])
            return 10 * max(dx, dy) + 4 * min(dx, dy)
        heap, dist, prev = [], {}, {}
        for (L, i, j) in src:
            if free(L, i, j):
                s = (L, i, j, 8)
                dist[s] = 0
                heapq.heappush(heap, (h(i, j), 0, 0, s))
        limit = DETOUR[0] * min((f for f, _, _, _ in heap), default=0) + DETOUR[1] / STEP * 10
        goal = None
        while heap:
            f, d, gl, s = heapq.heappop(heap)
            if d > dist.get(s, 1e18):
                continue
            L, i, j, dr = s
            if gl + h(i, j) > limit:
                continue
            if (L, i, j) in tree:
                goal = s
                break
            k0 = i * ny + j
            moves = []
            for nd_, (di, dj) in enumerate(DIRS):
                ni, nj = i + di, j + dj
                if not (0 <= ni < nx and 0 <= nj < ny) or not free(L, ni, nj):
                    continue
                if di and dj and not (free(L, i + di, j) or free(L, i, j + dj)):
                    continue
                step = 14 if di and dj else 10
                t = min((nd_ - dr) % 8, (dr - nd_) % 8)
                turn = 0 if dr == 8 else TURN[t] if t < 4 else 999
                moves.append((L, ni, nj, nd_, step, step + turn))
            if not via_bad[k0]:   # a via to the other layer here
                for L2 in range(nl):
                    if L2 != L and free(L2, i, j):
                        moves.append((L2, i, j, 8, 0, vcost))
            for L2, ni, nj, nd_, glen, cost in moves:
                n = (L2, ni, nj, nd_)
                k = ni * ny + nj
                nd = d + cost
                if glen and softc[L2][k] and not mine[L2][k]:
                    nd += glen * pres * softc[L2][k]
                hc = hist.get((L2, wi0 + ni, wj0 + nj))
                if hc and glen:
                    nd += glen * hc
                if not glen and softv[k]:   # a via crowding another signal net
                    nd += 20 * pres * softv[k]
                if nd < dist.get(n, 1e18):
                    dist[n] = nd
                    prev[n] = s
                    heapq.heappush(heap, (nd + h(ni, nj), nd, gl + glen, n))
        if goal is None:
            failed.append(name)
            continue
        path = [goal]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        path = [(L, i, j) for L, i, j, _ in path]
        paths.append(path)
        for c in path:
            tree.add(c)
            mine[c[0]][c[1] * ny + c[2]] = 1
        tree |= src
    segs, vias = [], []
    for p in paths:
        run = [p[0]]
        for c in p[1:] + [None]:
            if c is not None and c[0] == run[-1][0]:
                run.append(c)
                continue
            cellrun = [(i, j) for _, i, j in run]
            for a, b in straight_runs(cellrun):
                if a != b:
                    segs.append((LAYERS[run[0][0]], xy(*a), xy(*b)))
            if c is not None:   # layer change
                vias.append(xy(c[1], c[2]))
                run = [c]
    return segs, sorted(set(vias)), failed


def straight_runs(path):
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


def route_items(net, segs, vias):
    out = [LItem("seg", ((a, b), WIDTH), net, {L}, name="track") for L, a, b in segs]
    for v in vias:
        out.append(LItem("circ", (v, VIA[0] / 2), net, {"F", "B", "I"}, name="via"))
        out.append(LItem("circ", (v, VIA[1] / 2), net, (), hole=1))
    return out


class Router:
    def __init__(self, base):
        self.base = base
        self.routes = {}   # net -> (segs, vias)
        self.sig = Index([])

    def rebuild(self):
        self.sig = Index([it for n, (s, v) in self.routes.items() for it in route_items(n, s, v)])

    def put(self, net, route):
        self.routes[net] = route
        for it in route_items(net, *route):
            self.sig.add(it)

    def attempt(self, net, pts, ignore_signals=False, hist=None, pres=None):
        idxs = [self.base] if ignore_signals or pres is not None else [self.base, self.sig]
        soft = self.sig if pres is not None else None
        for m in WINDOW:
            win = (min(p[0] for p in pts) - m, min(p[1] for p in pts) - m, max(p[0] for p in pts) + m, max(p[1] for p in pts) + m)
            segs, vias, miss = route_net(net, idxs, win, soft, hist, pres or 0.0)
            if not miss:
                return segs, vias
        return None

    def blockers(self, net, route):
        """Other signal nets whose routes come closer than the real clearance."""
        out = set()
        for it in route_items(net, *route):
            if it.hole:
                continue
            for o in self.sig.query(it.bb[0] - 0.6, it.bb[1] - 0.6, it.bb[2] + 0.6, it.bb[3] + 0.6):
                if o.net == net or o.net in out or o.hole or not (it.layers & o.layers):
                    continue
                need = clr(o.net) - MARGIN
                if "via" in (it.name, o.name):
                    need = max(need, VIA_GAP)
                if gap_between(it, o) < need - 0.001:
                    out.add(o.net)
        return out


def gap_between(a, b):
    """Edge-to-edge distance of two track/via items."""
    def core(it):   # centreline (segment) and half width
        if it.kind == "seg":
            (p, q), w = it.geom
            return p, q, w / 2
        c, r = it.geom
        return c, c, r
    p1, q1, r1 = core(a)
    p2, q2, r2 = core(b)
    return seg_seg_dist(p1, q1, p2, q2) - r1 - r2


def connected(items):
    """True if a net's copper items form one piece."""
    if len(items) < 2:
        return True
    parent = list(range(len(items)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            A, B = items[a], items[b]
            if A.layers & B.layers and A.bb[0] <= B.bb[2] and B.bb[0] <= A.bb[2] and A.bb[1] <= B.bb[3] and B.bb[1] <= A.bb[3]:
                if any(A.dist(x, y) == 0 for x, y in sample(B)) or any(B.dist(x, y) == 0 for x, y in sample(A)):
                    parent[find(a)] = find(b)
    return len({find(a) for a in range(len(items))}) == 1


def main(path):
    board = pcbnew.LoadBoard(path)
    items = collect(board)
    by_net = defaultdict(list)
    for it in items:
        if not it.hole and it.net:
            by_net[it.net].append(it)
    todo = []
    for net, its in by_net.items():
        if not is_signal(net) or net == "~gap":
            continue
        pads = [it for it in its if it.name not in ("track", "via")]
        if len(pads) < 2 or connected(its):
            continue
        pts = [((it.bb[0] + it.bb[2]) / 2, (it.bb[1] + it.bb[3]) / 2) for it in pads]
        done, rest, L = [pts[0]], pts[1:], 0.0
        while rest:
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
    r = Router(Index(items))
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
            route = r.attempt(net, pts_of[net], hist=hist, pres=pres)
            if route is None:
                unroutable.append(net)
            else:
                r.put(net, route)
        conflicted = set()
        for net, route in r.routes.items():
            blk = r.blockers(net, route)
            if blk:
                conflicted |= blk | {net}
        for net in conflicted:
            for L, a, b in r.routes[net][0]:
                n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / STEP))
                for k in range(n + 1):
                    hist[(LAYERS.index(L), round((a[0] + (b[0] - a[0]) * k / n) / STEP), round((a[1] + (b[1] - a[1]) * k / n) / STEP))] += HIST_INC
        print(f"round {rnd + 1}: {len(r.routes)} routed, {len(conflicted)} overlapping ({time.time() - t0:.0f} s)", flush=True)
        if not conflicted:
            break
    while True:   # drop nets until the rest are legal
        cnt = {net: len(r.blockers(net, route)) for net, route in r.routes.items()}
        bad = [n for n, c in cnt.items() if c]
        if not bad:
            break
        r.routes.pop(max(bad, key=lambda n: (cnt[n], length[n])))
        r.rebuild()
    for _, net, pts in todo:   # retry the dropped nets
        if net not in r.routes and net not in unroutable:
            route = r.attempt(net, pts)
            if route is not None:
                r.put(net, route)
    for _, net, pts in todo:   # rip-up
        if net in r.routes or net in unroutable:
            continue
        free = r.attempt(net, pts, ignore_signals=True)
        if free is None:
            continue
        blk = r.blockers(net, free)
        saved = {b: r.routes.pop(b) for b in blk}
        r.rebuild()
        route = r.attempt(net, pts)
        ok = route is not None
        if ok:
            r.put(net, route)
            for b in sorted(blk, key=lambda n: length[n]):
                r2 = r.attempt(b, pts_of[b])
                if r2 is None:
                    ok = False
                    break
                r.put(b, r2)
        if not ok:
            for b in blk:
                r.routes.pop(b, None)
            r.routes.pop(net, None)
            r.routes.update(saved)
            r.rebuild()
        else:
            print(f"  rip-up: {net} routed, {len(blk)} net(s) moved", flush=True)
    lid = {"F": board.GetLayerID("F.Cu"), "B": board.GetLayerID("B.Cu")}
    n_vias = 0
    for net, (segs, vias) in sorted(r.routes.items()):
        ni = board.FindNet(net)
        for L, A, B in segs:
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(pcbnew.VECTOR2I(MM(A[0]), MM(A[1])))
            t.SetEnd(pcbnew.VECTOR2I(MM(B[0]), MM(B[1])))
            t.SetWidth(MM(WIDTH))
            t.SetLayer(lid[L])
            t.SetNet(ni)
            board.Add(t)
        for x, y in vias:
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
            v.SetWidth(MM(VIA[0]))
            v.SetDrill(MM(VIA[1]))
            v.SetNet(ni)
            board.Add(v)
            n_vias += 1
    board.Save(path)
    failed = sorted(net for _, net, _ in todo if net not in r.routes)
    print(f"via pass: {len(r.routes)} of {len(todo)} open signal nets routed on F.Cu/B.Cu, {n_vias} vias")
    if failed:
        print(f"not routed ({len(failed)}): " + " ".join(failed))


if __name__ == "__main__":
    main(sys.argv[1])
