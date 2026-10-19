#!/bin/sh
# Full rebuild: schematic -> JLC lookup -> fresh board -> sync -> placement ->
# placement-driven FPGA pin assignment -> schematic again -> resync nets.
# Needs KICAD_ROOT (unpacked KiCad AppImage, squashfs-root). Overwrites hardware/control_card.kicad_pcb.
# Pass --keep-io to keep the current reference/io_assignment.csv instead of recomputing it.
set -e
T=$(mktemp -d)
cd "$(dirname "$0")/.."
K="$KICAD_ROOT"
CLI="$K/AppRun kicad-cli"
PY="$K/AppRun python3.11 -I"
export KICAD_SYMBOL_DIR="$K/usr/share/kicad/symbols" KICAD_FOOTPRINT_DIR="$K/usr/share/kicad/footprints"
python3 -I tools/gen_schematic.py
python3 -I tools/jlc_bom.py > /dev/null
python3 -I tools/gen_schematic.py
$CLI sch export netlist --format kicadsexpr -o "$T/cc.net" hardware/control_card.kicad_sch > /dev/null
$PY tools/make_board.py hardware/control_card.kicad_pcb
$PY tools/sync_pcb.py "$T/cc.net" hardware/control_card.kicad_pcb
$PY tools/place.py hardware/control_card.kicad_pcb
if [ "$1" != "--keep-io" ]; then
    $PY tools/assign_io.py hardware/control_card.kicad_pcb
    $PY tools/assign_mux.py hardware/control_card.kicad_pcb
    python3 -I tools/gen_schematic.py
    $CLI sch export netlist --format kicadsexpr -o "$T/cc.net" hardware/control_card.kicad_sch > /dev/null
    $PY tools/sync_pcb.py "$T/cc.net" hardware/control_card.kicad_pcb
    # place again: which FPGA balls carry vias depends on the final pin assignment
    $PY tools/place.py hardware/control_card.kicad_pcb
fi
# stackup, layer roles, net classes; then BGA power vias and plane zones (filled by DRC below)
python3 -I tools/setup_board.py hardware/control_card.kicad_pcb
$PY tools/power_pours.py hardware/control_card.kicad_pcb
$PY tools/cell_copper.py hardware/control_card.kicad_pcb cells
$PY tools/tap_vias.py hardware/control_card.kicad_pcb
$PY tools/cell_copper.py hardware/control_card.kicad_pcb leftover
$PY tools/route_rails.py hardware/control_card.kicad_pcb
$PY tools/route_signals.py hardware/control_card.kicad_pcb
$PY tools/route_vias.py hardware/control_card.kicad_pcb
$CLI sch erc -o "$T/erc.rpt" hardware/control_card.kicad_sch | grep Found
$CLI pcb drc --refill-zones --save-board --schematic-parity -o "$T/drc.rpt" hardware/control_card.kicad_pcb | grep Found
echo "reports in $T"
