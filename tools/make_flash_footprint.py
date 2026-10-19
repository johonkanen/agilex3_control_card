"""BGA-24 6x8 mm (5x5, 1.0 mm) footprint with a 0.5 mm courtyard, for the MT25QU256ABA8E12 flash.

KiCad's stock BGA-24_6x8mm_Layout5x5_P1.0mm has a 1 mm courtyard margin (8x10 mm), which
does not fit the strip above the FPGA. Same pads, 0.5 mm courtyard.

    KICAD_FOOTPRINT_DIR=... squashfs-root/AppRun python3.11 -I tools/make_flash_footprint.py hardware/lib/control_card.pretty
"""
import os
import sys

import pcbnew


def main(out_dir):
    src = os.path.join(os.environ["KICAD_FOOTPRINT_DIR"], "Package_BGA.pretty")
    fp = pcbnew.FootprintLoad(src, "BGA-24_6x8mm_Layout5x5_P1.0mm")
    name = "BGA-24_6x8mm_Layout5x5_P1.0mm_CY0.5"
    fp.SetFPID(pcbnew.LIB_ID("control_card", name))
    fp.SetLibDescription("BGA-24 6x8 mm, 5x5 1.0 mm, 0.5 mm courtyard (Micron MT25Q TPBGA-24)")
    for item in list(fp.GraphicalItems()):
        if item.GetLayer() == pcbnew.F_CrtYd:
            fp.Remove(item)
    hx, hy = 3.0 + 0.5, 4.0 + 0.5
    pts = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy), (-hx, -hy)]
    for a, b in zip(pts, pts[1:]):
        s = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(a[0]), pcbnew.FromMM(a[1])))
        s.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(b[0]), pcbnew.FromMM(b[1])))
        s.SetLayer(pcbnew.F_CrtYd)
        s.SetWidth(pcbnew.FromMM(0.05))
        fp.Add(s)
    fp.SetValue(name)
    pcbnew.PCB_IO_KICAD_SEXPR().FootprintSave(os.path.abspath(out_dir), fp)
    print("wrote", name)


if __name__ == "__main__":
    main(sys.argv[1])
