#!/bin/sh
# JLCPCB order files from the current board, into hardware/fab/ (see tools/jlc/fab_outputs.sh):
#   control_card_gerbers.zip   Gerbers (6 copper layers, mask, paste, silk, edge) + Excellon drill (PTH/NPTH)
#   bom_jlcpcb.csv, cpl_jlcpcb.csv   assembly BOM and placement (J1/J2 left out: soldered by hand)
#   drc.rpt                    DRC with the board's rules (incl. the JLC rules in control_card.kicad_dru)
# Needs KICAD_ROOT (unpacked KiCad AppImage, squashfs-root) and the tools/jlc submodule
# (git submodule update --init). Extra args replace the default --skip J1,J2, e.g. --skip J1,J2,U1.
set -e
cd "$(dirname "$0")/.."
[ $# -gt 0 ] || set -- --skip J1,J2
exec tools/jlc/fab_outputs.sh hardware/control_card.kicad_pcb hardware/fab "$@"
