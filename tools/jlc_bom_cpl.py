"""JLCPCB assembly files from the board: BOM (Comment, Designator, Footprint, LCSC Part #) and
CPL (Designator, Mid X, Mid Y, Layer, Rotation).

    squashfs-root/AppRun python3.11 -I tools/jlc_bom_cpl.py hardware/control_card.kicad_pcb pos.csv out_dir [--skip REF,...]

pos.csv is KiCad's position file (kicad-cli pcb export pos --format csv --units mm --side both).
Left out of both files: footprints marked DNP or "exclude from BOM", footprints without pads
(logos, fiducial-less graphics), and the --skip references (default J1,J2: the connectors are
soldered by hand). Parts without an LCSC number stay in the BOM with an empty LCSC column, so
JLCPCB's Global Sourcing or consigned parts can be matched to them; they are listed at the end.
"""
import csv
import os
import sys
from collections import OrderedDict

import pcbnew


def main(pcb, pos_csv, out_dir, skip):
    board = pcbnew.LoadBoard(pcb)
    rows = OrderedDict()
    fitted = set()
    no_lcsc = []
    for fp in sorted(board.GetFootprints(), key=lambda f: (f.GetReference()[0], len(f.GetReference()), f.GetReference())):
        ref = fp.GetReference()
        if ref in skip or ref.startswith("#") or fp.IsDNP() or fp.IsExcludedFromBOM() or not any(p.GetNumber() for p in fp.Pads()):
            continue
        lcsc = fp.GetFieldText("LCSC") if fp.HasField("LCSC") else ""
        mpn = fp.GetFieldText("MPN") if fp.HasField("MPN") else ""
        comment = mpn or fp.GetValue()
        key = (comment, str(fp.GetFPID().GetLibItemName()), lcsc)
        rows.setdefault(key, []).append(ref)
        fitted.add(ref)
        if not lcsc:
            no_lcsc.append(f"{ref} ({comment})")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "bom_jlcpcb.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (comment, footprint, lcsc), refs in rows.items():
            w.writerow([comment, ",".join(refs), footprint, lcsc])
    n = 0
    with open(pos_csv) as f, open(os.path.join(out_dir, "cpl_jlcpcb.csv"), "w", newline="") as g:
        w = csv.writer(g)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in csv.DictReader(f):
            if r["Ref"] in fitted:
                side = "Top" if r["Side"].lower().startswith("top") else "Bottom"
                w.writerow([r["Ref"], f"{float(r['PosX']):.4f}mm", f"{float(r['PosY']):.4f}mm", side,
                            f"{float(r['Rot']):.1f}"])
                n += 1
    print(f"BOM: {len(rows)} lines, {len(fitted)} parts; CPL: {n} placements; left out: {', '.join(sorted(skip))}")
    if n != len(fitted):
        print("warning: the position file is missing", len(fitted) - n, "fitted part(s)")
    if no_lcsc:
        print("no LCSC number (Global Sourcing / consigned):", ", ".join(no_lcsc))


if __name__ == "__main__":
    args = sys.argv[1:]
    skip = {"J1", "J2"}
    if "--skip" in args:
        i = args.index("--skip")
        skip = {s for s in args[i + 1].split(",") if s}
        del args[i:i + 2]
    main(*args, skip)
