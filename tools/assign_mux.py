"""Choose which mux input takes which analog header signal, to minimise crossing routes.

    squashfs-root/AppRun python3.11 -I tools/assign_mux.py hardware/control_card.kicad_pcb

The FPGA can renumber mux channels freely, so the 7 analog inputs of each 4051 (ADA0-6 on
U10, ADB0-6 on U13) can go to any of its 8 inputs X0-X7; the remaining input is grounded
(zero reference). For each mux every permutation is scored by the number of crossings between
the straight J1-pad -> mux-pad lines (both on the mux's side of the board), then by total
length. Writes reference/mux_assignment.csv (mux, x_input, pin, net): this is also the channel
table for the FPGA, and tools/gen_schematic.py wires the muxes from it.
"""
import csv
import itertools
import math
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "reference", "mux_assignment.csv")
X_PINS = ["13", "14", "15", "12", "1", "5", "2", "4"]   # 4051 X0..X7


def cross(a, b, c, d):
    """True if segments ab and cd properly intersect."""
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (v > 1e-9) - (v < -1e-9)
    return orient(a, b, c) * orient(a, b, d) < 0 and orient(c, d, a) * orient(c, d, b) < 0


def pos(pad):
    p = pad.GetPosition()
    return pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)


def main(path):
    board = pcbnew.LoadBoard(path)
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    j1 = {p.GetNetname(): pos(p) for p in fps["J1"].Pads()}
    rows = []
    for prefix in ("ADA", "ADB"):
        nets = [f"{prefix}{i}" for i in range(7)]
        mux = next(f for f in fps.values() if "TSSOP-16" in f.GetFPIDAsString()
                   and any(p.GetNetname() in nets for p in f.Pads()))
        mpos = {p.GetNumber(): pos(p) for p in mux.Pads()}
        src = [j1[n] for n in nets]
        best = None
        for perm in itertools.permutations(X_PINS, 7):
            segs = [(src[i], mpos[perm[i]]) for i in range(7)]
            c = sum(cross(*segs[i], *segs[j]) for i in range(7) for j in range(i + 1, 7))
            length = sum(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in segs)
            key = (c, length)
            if best is None or key < best[0]:
                best = (key, perm)
        (c, length), perm = best
        gnd_pin = next(p for p in X_PINS if p not in perm)
        assign = {perm[i]: nets[i] for i in range(7)}
        assign[gnd_pin] = "GND"
        for x, pin in enumerate(X_PINS):
            rows.append(dict(mux=mux.GetReference(), x_input=f"X{x}", pin=pin, net=assign[pin]))
        print(f"{mux.GetReference()}: {c} crossings, {length:.1f} mm; "
              + " ".join(f"X{x}={assign[p]}" for x, p in enumerate(X_PINS)))
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["mux", "x_input", "pin", "net"])
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main(sys.argv[1])
