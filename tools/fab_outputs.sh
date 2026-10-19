#!/bin/sh
# JLCPCB order files from the current board, into hardware/fab/:
#   control_card_gerbers.zip   Gerbers (6 copper layers, mask, paste, silk, edge) + Excellon drill (PTH/NPTH)
#   bom_jlcpcb.csv, cpl_jlcpcb.csv   assembly BOM and placement (J1/J2 left out: soldered by hand)
#   drc.rpt                    DRC with the board's rules (incl. the JLC rules in control_card.kicad_dru)
# Needs KICAD_ROOT (unpacked KiCad AppImage, squashfs-root). Read-only on the board: zones are refilled
# for plotting only. Pass extra args to jlc_bom_cpl.py, e.g. --skip J1,J2,U1 to leave the FPGA out too.
set -e
cd "$(dirname "$0")/.."
K="$KICAD_ROOT"
CLI="$K/AppRun kicad-cli"
PY="$K/AppRun python3.11 -I"
PCB=hardware/control_card.kicad_pcb
OUT=hardware/fab
T=$(mktemp -d)
rm -rf "$OUT"
mkdir -p "$OUT" "$T/gerber"
$CLI pcb drc --refill-zones --schematic-parity -o "$OUT/drc.rpt" "$PCB" | grep Found || true
$CLI pcb export gerbers --check-zones --subtract-soldermask -o "$T/gerber" \
    --layers F.Cu,In1.Cu,In2.Cu,In3.Cu,In4.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts "$PCB" > /dev/null
$CLI pcb export drill --format excellon --excellon-units mm --excellon-zeros-format decimal \
    --excellon-separate-th -o "$T/gerber/" "$PCB" > /dev/null
(cd "$T/gerber" && python3 -c "import sys, zipfile, os; z = zipfile.ZipFile(sys.argv[1], 'w', zipfile.ZIP_DEFLATED); [z.write(f) for f in sorted(os.listdir('.'))]" "$OLDPWD/$OUT/control_card_gerbers.zip")
ls "$T/gerber"
$CLI pcb export pos --format csv --units mm --side both -o "$T/pos.csv" "$PCB" > /dev/null
$PY tools/jlc_bom_cpl.py "$PCB" "$T/pos.csv" "$OUT" "$@"
echo "files in $OUT"
