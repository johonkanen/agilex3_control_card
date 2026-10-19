"""Build the Altera B18A (474-ball, 18 x 18 mm) footprint from Altera's ball table.

Run with KiCad's bundled Python:
    squashfs-root/AppRun python3.11 -I tools/make_bga_footprint.py \
        reference/altera-pbc-b18a-a5e-a3c-1p1.csv hardware/lib/control_card.pretty

The ball table comes from Rolf-Altera/kicad-library-tools (Altera's B18A ball
coordinates). As in that generator, x is flipped to get the top view. Pad, mask
and paste sizes copy agilex3_control_card_v1, which was built and works:
0.30 mm NSMD copper, 0.35 mm mask opening, 0.30 mm paste.
"""
import csv
import os
import sys

import pcbnew

BODY = 18.0
PAD = 0.30
MASK_EXPANSION = 0.025
COURTYARD_MARGIN = 1.0
NAME = "Altera_B18A"


def mm(v):
    return pcbnew.FromMM(v)


def v(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def poly(fp, layer, pts, width):
    for a, b in zip(pts, pts[1:]):
        s = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(v(*a))
        s.SetEnd(v(*b))
        s.SetLayer(layer)
        s.SetWidth(mm(width))
        fp.Add(s)


def main(table, out_dir):
    fp = pcbnew.FOOTPRINT(None)
    fp.SetFPID(pcbnew.LIB_ID("control_card", NAME))
    fp.SetLibDescription("Altera B18A 474-ball variable-pitch BGA, 18x18 mm "
                         "(Agilex 3 C-series / Agilex 5 E-series)")
    fp.SetKeywords("BGA Altera Agilex B18A")
    fp.SetAttributes(pcbnew.FP_SMD)

    for row in csv.DictReader(open(table)):
        pad = pcbnew.PAD(fp)
        pad.SetNumber(row["pin_number"])
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetLayerSet(pad.SMDMask())
        pad.SetSize(v(PAD, PAD))
        pad.SetLocalSolderMaskMargin(mm(MASK_EXPANSION))
        pad.SetPosition(v(-float(row["position_x"]), float(row["position_y"])))
        fp.Add(pad)

    h = BODY / 2
    c = 1.0  # pin-1 chamfer on the fab outline
    poly(fp, pcbnew.F_Fab, [(-h + c, -h), (h, -h), (h, h), (-h, h), (-h, -h + c), (-h + c, -h)], 0.1)
    s = h + 0.11
    poly(fp, pcbnew.F_SilkS, [(-s, -s + 1.5), (-s, -s), (-s + 1.5, -s)], 0.12)
    poly(fp, pcbnew.F_SilkS, [(s - 1.5, -s), (s, -s), (s, -s + 1.5)], 0.12)
    poly(fp, pcbnew.F_SilkS, [(s, s - 1.5), (s, s), (s - 1.5, s)], 0.12)
    poly(fp, pcbnew.F_SilkS, [(-s + 1.5, s), (-s, s), (-s, s - 1.5)], 0.12)
    k = h + COURTYARD_MARGIN
    poly(fp, pcbnew.F_CrtYd, [(-k, -k), (k, -k), (k, k), (-k, k), (-k, -k)], 0.05)

    fp.Reference().SetPosition(v(0, -k - 1))
    fp.Value().SetText(NAME)
    fp.Value().SetPosition(v(0, k + 1))
    fp.Value().SetLayer(pcbnew.F_Fab)

    os.makedirs(out_dir, exist_ok=True)
    pcbnew.PCB_IO_KICAD_SEXPR().FootprintSave(os.path.abspath(out_dir), fp)
    print(f"wrote {out_dir}/{NAME}.kicad_mod with {len(fp.Pads())} pads")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
