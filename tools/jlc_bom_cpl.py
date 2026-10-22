"""JLCPCB assembly files from the board: BOM (Comment, Designator, Footprint, LCSC Part #) and
CPL (Designator, Mid X, Mid Y, Layer, Rotation).

    squashfs-root/AppRun python3.11 -I tools/jlc_bom_cpl.py hardware/control_card.kicad_pcb pos.csv out_dir [--skip REF,...]

pos.csv is KiCad's position file (kicad-cli pcb export pos --format csv --units mm --side both).
Left out of both files: footprints marked DNP or "exclude from BOM", footprints without pads
(logos, fiducial-less graphics), and the --skip references (default J1,J2: the connectors are
soldered by hand). Parts without an LCSC number stay in the BOM with an empty LCSC column, so
JLCPCB's Global Sourcing or consigned parts can be matched to them; they are listed at the end.

CPL rotations are converted to JLCPCB's convention, as kicad-jlcpcb-tools and JLCKicadTools do:
- bottom-side parts are placed as seen from below, so KiCad's angle a becomes 180 - a;
- JLC's footprint models for some packages are drawn rotated from KiCad's. ROTATION_CORRECTIONS
  holds the usual offsets by footprint name, added on top and subtracted on the bottom;
- a footprint field "JLC Rotation Offset" (degrees) replaces the table offset for that part, for
  fixes found in JLC's placement preview.
Check the result in JLC's placement preview anyway: packages not in the table keep offset 0.
"""
import csv
import os
import re
import sys
from collections import OrderedDict

import pcbnew

# (footprint name regex, offset in degrees): the correction table of kicad-jlcpcb-tools / JLCKicadTools
ROTATION_CORRECTIONS = [
    (r"^SOT-223", 180),
    (r"^SOT-23", 180),
    (r"^SOT-353", 180),
    (r"^SOT-89", 180),
    (r"^QFN-", 270),
    (r"^(.*?_|V)?QFN-(16|20|24|28|40)(-|_|$)", 270),
    (r"^DFN-", 270),
    (r"^LQFP-", 270),
    (r"^TQFP-", 270),
    (r"^SOIC-", 270),
    (r"^SOP-(?!18_)", 270),
    (r"^TSSOP-", 270),
    (r"^HTSSOP-", 270),
    (r"^VSSOP-", 270),
    (r"^MSOP-", 270),
    (r"^LED_WS2812B_PLCC4", 180),
]


def jlc_rotation(fp, kicad_rot):
    """JLC CPL rotation and the offset applied, from the KiCad angle and footprint."""
    name = str(fp.GetFPID().GetLibItemName())
    if fp.HasField("JLC Rotation Offset") and fp.GetFieldText("JLC Rotation Offset").strip():
        offset = float(fp.GetFieldText("JLC Rotation Offset"))
    else:
        offset = next((o for pat, o in ROTATION_CORRECTIONS if re.search(pat, name)), 0)
    if fp.IsFlipped():
        rot = 180 - kicad_rot - offset
    else:
        rot = kicad_rot + offset
    return rot % 360, offset


def main(pcb, pos_csv, out_dir, skip):
    board = pcbnew.LoadBoard(pcb)
    rows = OrderedDict()
    fitted = {}
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
        fitted[ref] = fp
        if not lcsc:
            no_lcsc.append(f"{ref} ({comment})")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "bom_jlcpcb.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (comment, footprint, lcsc), refs in rows.items():
            w.writerow([comment, ",".join(refs), footprint, lcsc])
    n = 0
    corrected = []
    with open(pos_csv) as f, open(os.path.join(out_dir, "cpl_jlcpcb.csv"), "w", newline="") as g:
        w = csv.writer(g)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in csv.DictReader(f):
            if r["Ref"] in fitted:
                side = "Top" if r["Side"].lower().startswith("top") else "Bottom"
                rot, offset = jlc_rotation(fitted[r["Ref"]], float(r["Rot"]))
                if offset:
                    corrected.append(f"{r['Ref']} {offset:+g}")
                w.writerow([r["Ref"], f"{float(r['PosX']):.4f}mm", f"{float(r['PosY']):.4f}mm", side, f"{rot:.1f}"])
                n += 1
    print(f"BOM: {len(rows)} lines, {len(fitted)} parts; CPL: {n} placements; left out: {', '.join(sorted(skip))}")
    print("rotation: bottom side as seen from below (180 - angle); package offsets:", ", ".join(corrected) or "none")
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
