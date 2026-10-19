"""Assign FPGA HVIO balls from the placement: each signal goes to the ball nearest the pad it drives.

    squashfs-root/AppRun python3.11 -I tools/assign_io.py hardware/control_card.kicad_pcb

For every net on an FPGA HVIO ball, the target is the nearest other pad on that net
(J1 pin, series resistor, HyperRAM ball, ...). Signals are matched to the 160 HVIO
balls by a minimum-cost assignment (Hungarian algorithm). Cost = distance from ball
to target plus a small penalty for balls deep inside the array (harder to escape).

Constraints:
- CLK100M only on a PLLREFCLK ball (dedicated clock input).
- All HyperRAM signals (HR_*) in bank HR_BANK (6C, 1.8 V) and nothing else there; the 1.8 V clock CLK100M alone in
  CLK_BANK (6D, 1.8 V, PLLREFCLK1 D18 on the outer edge).

Writes reference/io_assignment.csv (net, ball, bank, target, distance). Then rerun
tools/gen_schematic.py, which uses that file, and resync the board.
"""
import csv
import math
import os
import re
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "reference", "io_assignment.csv")
DEPTH_WEIGHT = 0.5    # mm of cost per mm the ball sits inside the outer ring
# hand swaps after the matching (same bank, applied in order), so the J1 fan-out routes on L1
# without crossings: the outer/inner ball pair of each J1 column pair is swapped to match J1's
# odd/even rows. BL51 can only leave west, past BM50, so it takes BM50's signal (CUK_CS, J1.7)
BALL_SWAPS = [("BM8", "BN8"), ("BL51", "BM51"), ("BM29", "BN29"), ("BM42", "BN42"), ("BL51", "BM50"), ("V1", "M2")]
# The HyperRAM is 1.8 V, so its bank runs VCCIO at 1.8 V (gen_schematic.py ties VCCIO_HVIO_6C/6D to +1V8_HR) and
# carries nothing else; every other signal here is 3.3 V.
HR_BANK = "6C"
CLK_BANK = "6D"


def hungarian(cost):
    """Minimum-cost assignment for an n x m matrix, n <= m. Returns column index per row."""
    n, m = len(cost), len(cost[0])
    INF = float("inf")
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    res = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            res[p[j] - 1] = j - 1
    return res


def main(path):
    board = pcbnew.LoadBoard(path)
    fpga = next(fp for fp in board.GetFootprints() if fp.GetReference() == "U1")
    cx, cy = (pcbnew.ToMM(v) for v in (fpga.GetPosition().x, fpga.GetPosition().y))
    lib = open(os.path.join(HERE, "..", "hardware", "lib", "agilex3.kicad_sym")).read()
    func = {num: name for name, num in
            re.findall(r'\(name "([^"]*)".*?\(number "([^"]*)"', lib, re.S)}   # ball -> symbol pin name
    balls = {}  # HVIO ball -> (x, y, bank, pin function)
    for pad in fpga.Pads():
        m = re.match(r"(6[A-H])_IO_HVIO", func.get(pad.GetNumber(), ""))
        if m:
            x, y = (pcbnew.ToMM(v) for v in (pad.GetPosition().x, pad.GetPosition().y))
            balls[pad.GetNumber()] = (x, y, m.group(1), func[pad.GetNumber()])
    nets = {}
    for pad in fpga.Pads():
        if pad.GetNumber() in balls and pad.GetNetname() and not pad.GetNetname().startswith("unconnected"):
            nets[pad.GetNetname()] = None
    for net in nets:
        best = None
        for fp in board.GetFootprints():
            if fp.GetReference() == "U1":
                continue
            for pad in fp.Pads():
                if pad.GetNetname() == net:
                    x, y = (pcbnew.ToMM(v) for v in (pad.GetPosition().x, pad.GetPosition().y))
                    d = math.hypot(x - cx, y - cy)
                    if best is None or d < best[0]:
                        best = (d, x, y, f"{fp.GetReference()}.{pad.GetNumber()}")
        nets[net] = best
    signals = sorted(n for n in nets if nets[n])
    ball_ids = sorted(balls)
    half = 9.0

    def cost(net, b):
        x, y, bank, func = balls[b]
        if net.endswith("CLK100M") and "PLLREFCLK" not in func:
            return 1e6
        _, tx, ty, _ = nets[net]
        depth = half - max(abs(x - cx), abs(y - cy))
        return math.hypot(x - tx, y - ty) + DEPTH_WEIGHT * max(depth, 0.0)

    best = None
    for hr_bank in [HR_BANK]:
        mat = []
        for net in signals:
            row = []
            for b in ball_ids:
                c = cost(net, b)
                if net.startswith("HR_") != (balls[b][2] == hr_bank) or net.endswith("CLK100M") != (balls[b][2] == CLK_BANK):
                    c = 1e6
                row.append(c)
            mat.append(row)
        sol = hungarian(mat)
        total = sum(mat[i][j] for i, j in enumerate(sol))
        if best is None or total < best[0]:
            best = (total, hr_bank, sol)
    total, hr_bank, sol = best
    if total >= 1e6:
        raise SystemExit("no feasible assignment")
    ball_of = {signals[i]: ball_ids[j] for i, j in enumerate(sol)}
    net_on = {b: n for n, b in ball_of.items()}
    for a, b in BALL_SWAPS:
        na, nb = net_on.get(a), net_on.get(b)
        if na:
            ball_of[na] = b
        if nb:
            ball_of[nb] = a
    rows = []
    for net, b in ball_of.items():
        x, y, bank, func = balls[b]
        _, tx, ty, tgt = nets[net]
        rows.append(dict(net=net, ball=b, bank=bank, target=tgt, distance=round(math.hypot(x - tx, y - ty), 2)))
    rows.sort(key=lambda r: (r["bank"], r["net"]))
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["net", "ball", "bank", "target", "distance"])
        w.writeheader()
        w.writerows(rows)
    banks = {}
    for r in rows:
        banks[r["bank"]] = banks.get(r["bank"], 0) + 1
    print(f"{len(rows)} signals, HyperRAM in bank {hr_bank}, total cost {total:.1f}, per bank {dict(sorted(banks.items()))}")


if __name__ == "__main__":
    main(sys.argv[1])
