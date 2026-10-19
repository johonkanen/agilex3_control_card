"""Create the bare PCB: U25 outline, 6 copper layers, J1 and J2 at the U25 positions.

Run with KiCad's bundled Python, e.g.
    squashfs-root/AppRun python3.11 -I tools/make_board.py hardware/control_card.kicad_pcb

Coordinates come from the Proteus Gerbers of u25_v2 / ecp5_bga381_v1_1 (identical
outline and connector positions). Gerber y points up, KiCad y points down, so
KiCad (x, y) = (ORIGIN_X + gx, ORIGIN_Y - gy). The aux and grid origins sit on the
Gerber origin so plots with "use drill/place file origin" match the old files.
"""
import os
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fp_uuid import set_stable_uuid  # noqa: E402

ORIGIN_X, ORIGIN_Y = 100.0, 100.0
PROJECT_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hardware", "lib", "control_card.pretty")

# Board outline in Gerber coordinates (mm), from the Mechanical 1 profile.
OUTLINE = (-24.8, -28.7, 7.738, 5.1)  # x0, y0, x1, y1

# (ref, library, footprint, pin1 gerber xy, pin2 gerber xy)
CONNECTORS = [
    # project copy with U25's smaller pads/drills, so a track fits between the pins
    ("J1", "control_card", "PinHeader_2x25_P1.27mm_Horizontal_U25",
     (6.619, -26.254), (6.619, -27.524)),
    ("J2", "Connector_PinHeader_2.54mm", "PinHeader_1x05_P2.54mm_Vertical",
     (4.888, 2.159), (4.888, -0.381)),
]


def mm(v):
    return pcbnew.FromMM(v)


def pt(gx, gy):
    return pcbnew.VECTOR2I(mm(ORIGIN_X + gx), mm(ORIGIN_Y - gy))


def add_outline(board):
    x0, y0, x1, y1 = OUTLINE
    corners = [pt(x0, y0), pt(x1, y0), pt(x1, y1), pt(x0, y1)]
    for a, b in zip(corners, corners[1:] + corners[:1]):
        seg = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(a)
        seg.SetEnd(b)
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(mm(0.1))
        board.Add(seg)


def place(board, fp_dir, ref, lib, name, pin1, pin2):
    path = PROJECT_LIB if lib == "control_card" else os.path.join(fp_dir, lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    fp.SetReference(ref)
    set_stable_uuid(fp, ref)
    board.Add(fp)
    want1, want2 = pt(*pin1), pt(*pin2)
    # Try the four orientations and keep the one where pads 1 and 2 land on target.
    for deg in (0, 90, 180, 270):
        fp.SetOrientationDegrees(deg)
        fp.SetPosition(pcbnew.VECTOR2I(0, 0))
        p1 = fp.FindPadByNumber("1").GetPosition()
        fp.SetPosition(pcbnew.VECTOR2I(want1.x - p1.x, want1.y - p1.y))
        got2 = fp.FindPadByNumber("2").GetPosition()
        if abs(got2.x - want2.x) < mm(0.01) and abs(got2.y - want2.y) < mm(0.01):
            fp.SetLocked(True)
            return deg
    raise RuntimeError(f"{ref}: no orientation matches pin 1/2 positions")


def main(out):
    fp_dir = os.environ.get("KICAD_FOOTPRINT_DIR") or os.path.join(
        os.path.dirname(sys.executable), "..", "share", "kicad", "footprints")
    board = pcbnew.NewBoard(out)
    board.SetCopperLayerCount(6)
    board.GetDesignSettings().SetBoardThickness(mm(1.6))
    add_outline(board)
    origin = pt(0, 0)
    board.GetDesignSettings().SetAuxOrigin(origin)
    board.GetDesignSettings().SetGridOrigin(origin)
    for ref, lib, name, p1, p2 in CONNECTORS:
        deg = place(board, fp_dir, ref, lib, name, p1, p2)
        print(f"{ref}: {lib}:{name} rotated {deg} deg")
    board.Save(out)
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1])
