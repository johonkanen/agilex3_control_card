"""Footprint for the Kingbright APFA3010LSEEZGKQBKC right-angle (side-view) common-anode RGB LED
(LCSC C5393554), the LED U25 used: 3.0 x 1.5 x 1.0 mm, light parallel to the board.

Pads from the datasheet's recommended soldering pattern: the two end terminals 1.0 x 0.9 mm with
centres 3.0 mm apart (4.0 mm overall), the two rear terminals 0.4 x 0.8 mm at 0.8 mm pitch, spanning
0.05-0.85 mm behind the end pads' centre line. The lens points to -y (north at 0 degrees). Top view,
lens up: pad 1 (red cathode) left, pad 2 (anode) right, rear pads 4 (blue) left and 3 (green) right.
U25 placed the end-pad centres 1.8 mm from the board edge, which puts the lens tip about 0.55 mm
inside it. Courtyard 0.1 mm around pads and lens (IPC least), so D2 leaves the packer's
0.05 mm gap to the HyperRAM courtyard at x 84.0.

    squashfs-root/AppRun python3.11 -I tools/make_led_footprint.py hardware/lib/control_card.pretty
"""
import os
import sys

import pcbnew

NAME = "LED_RGB_APFA3010_RightAngle"
BODY = (-0.25, 0.25)     # y extent of the 3.0 mm body strip; the 2.0 mm wide lens dome is 1.0 mm in front


def mm(v):
    return pcbnew.FromMM(v)


def line(fp, layer, a, b, w):
    s = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(pcbnew.VECTOR2I(mm(a[0]), mm(a[1])))
    s.SetEnd(pcbnew.VECTOR2I(mm(b[0]), mm(b[1])))
    s.SetLayer(layer)
    s.SetWidth(mm(w))
    fp.Add(s)


def rect(fp, layer, x0, y0, x1, y1, w):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    for a, b in zip(pts, pts[1:]):
        line(fp, layer, a, b, w)


def main(out_dir):
    fp = pcbnew.FOOTPRINT(None)
    fp.SetFPID(pcbnew.LIB_ID("control_card", NAME))
    fp.SetLibDescription("Kingbright APFA3010LSEEZGKQBKC right-angle common-anode RGB LED, 3.0x1.5x1.0 mm "
                         "(LCSC C5393554); lens toward -y")
    fp.SetAttributes(pcbnew.FP_SMD)
    for num, x, y, w, h in (("1", -1.5, 0.0, 1.0, 0.9), ("2", 1.5, 0.0, 1.0, 0.9),
                            ("4", -0.4, 0.45, 0.4, 0.8), ("3", 0.4, 0.45, 0.4, 0.8)):
        p = pcbnew.PAD(fp)
        p.SetNumber(num)
        p.SetShape(pcbnew.PAD_SHAPE_RECT)
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        p.SetLayerSet(p.SMDMask())
        p.SetSize(pcbnew.VECTOR2I(mm(w), mm(h)))
        p.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        fp.Add(p)
    rect(fp, pcbnew.F_Fab, -1.5, BODY[0], 1.5, BODY[1], 0.1)
    arc = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_ARC)   # lens dome, 2.0 mm wide, 1.0 mm deep
    arc.SetArcGeometry(pcbnew.VECTOR2I(mm(-1.0), mm(BODY[0])), pcbnew.VECTOR2I(0, mm(BODY[0] - 1.0)),
                       pcbnew.VECTOR2I(mm(1.0), mm(BODY[0])))
    arc.SetLayer(pcbnew.F_Fab)
    arc.SetWidth(mm(0.1))
    fp.Add(arc)
    rect(fp, pcbnew.F_CrtYd, -2.1, BODY[0] - 1.0 - 0.1, 2.1, 0.85 + 0.1, 0.05)
    dot = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_CIRCLE)   # anode (pad 2) marker behind the pad
    dot.SetCenter(pcbnew.VECTOR2I(mm(1.5), mm(0.85)))
    dot.SetEnd(pcbnew.VECTOR2I(mm(1.6), mm(0.85)))
    dot.SetLayer(pcbnew.F_SilkS)
    dot.SetWidth(mm(0.2))
    fp.Add(dot)
    fp.Reference().SetPosition(pcbnew.VECTOR2I(0, mm(1.7)))
    fp.Value().SetText(NAME)
    fp.Value().SetLayer(pcbnew.F_Fab)
    fp.Value().SetPosition(pcbnew.VECTOR2I(0, mm(2.4)))
    pcbnew.PCB_IO_KICAD_SEXPR().FootprintSave(os.path.abspath(out_dir), fp)
    print("wrote", NAME)


if __name__ == "__main__":
    main(sys.argv[1])
