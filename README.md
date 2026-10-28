# Agilex 3 control card

A small FPGA control card built around an Altera Agilex 3 (A3CZ065BB18AE7S, B18A BGA), designed in KiCad 10. It plugs
into a power-electronics board through a 2×25 1.27 mm header and replaces an older Cyclone 10 card (U25) with the same
outline and connector positions.

| Top | Bottom |
|---|---|
| ![Top side](docs/img/board_top.png) | ![Bottom side](docs/img/board_bottom.png) |

**Status: ready to order (2026-10-22).** The design is complete and fully routed; DRC is clean and the board matches the
schematic. It passed three independent reviews (production files against JLCPCB's capabilities, electrical design, and the
Agilex 3 configuration against Altera's guidelines and two evaluation-kit schematics). The FPGAs are being bought through
JLCPCB Global Sourcing; the assembly order follows when they reach JLC's warehouse. The board has not been built or tested
yet: `docs/bringup_checklist.md` is the plan for when it arrives.

## Features

- **FPGA:** Agilex 3 A3CZ065, 65k logic elements, speed grade −7, extended temperature. 63 I/O signals, mostly on 3.3 V HVIO
  banks with no level shifters.
- **Memory:** 32 MB HyperRAM (Winbond W958D8NBYA5I, 1.8 V) on bank 6D. The W959D8NFYA5I (64 MB) fits the same footprint.
- **Configuration:** Active Serial x4 from a 1.8 V QSPI flash (Micron MT25QU256). JTAG on a 5-pin 2.54 mm header,
  shifted from 3.3 V to 1.8 V by an SN74AVC4T774.
- **Clock:** 100 MHz 1.8 V oscillator into PLLREFCLK1 (D18) and the configuration clock input OSC_CLK_1.
- **ADC:** 2 channels, each an 8:1 analog mux (SN74LV4051A) → OPA365 buffer → ADS7056 (14-bit, 2.5 MSPS), on a separate
  analog 3.3 V supply.
- **Power:** from 5 V on the header. Three Diodes AP61x02 bucks (0.753 V core with remote sense, 1.8 V, 3.3 V) start up in order, each
  enabled by the previous one's power-good. LDOs make 1.2 V, analog 3.3 V and a separate 1.8 V for the HyperRAM bank.
  The FPGA's PLL and ADC supplies are filtered with ferrite beads.
- **Indicators:** 2 RGB LEDs.
- **Board:** 32.5 × 33.8 mm, 6 layers, 1.6 mm (JLC stackup JLC06161H-3313), ENIG, 0.65 mm-pitch BGA fanned out with
  filled and capped via-in-pad. 146 parts assembled by JLCPCB on both sides (37 top, 109 bottom); the headers J1 and J2
  are soldered by hand.

## Repository layout

| Path | Contents |
|---|---|
| `hardware/` | KiCad project: schematic (`control_card.kicad_sch` plus `sheets/`), board, design rules (`control_card.kicad_dru` adds JLCPCB limits) |
| `hardware/lib/` | Project symbols and footprints, including the Agilex 3 symbol and the B18A BGA footprint |
| `reference/` | FPGA pin assignment (`pin_assignment.csv`), Altera pin lists, power-board header pinout, JLCPCB part list |
| `docs/` | Design notes, Agilex 3 board requirements, flash requirements, production and bring-up checklists, board renders |
| `tools/` | Python scripts that generated the schematic and board, plus the fabrication-output wrapper |
| `tools/jlc/` | Submodule [jlc-tools](https://github.com/johonkanen/jlc-tools): JLC part search, stock check, BOM/CPL and Gerber export |

## Documentation

- [`docs/design-notes.md`](docs/design-notes.md): architecture, part choices and the reasons for them.
- [`docs/agilex3_requirements.md`](docs/agilex3_requirements.md): what the FPGA needs from the board (supply rails,
  bank voltages, power-up order, configuration pins) and how this card meets each requirement.
- [`docs/agilex_flash_requirements.md`](docs/agilex_flash_requirements.md): configuration flash requirements.
- [`docs/jlcpcb_production_checklist.md`](docs/jlcpcb_production_checklist.md): verifying the design and order files
  against JLCPCB's capabilities, plus the order-form settings.
- [`docs/bringup_checklist.md`](docs/bringup_checklist.md): testing the assembled boards, from inspection and first
  power-up to configuration, HyperRAM, ADCs and the power-board interface.
- [`docs/order_checklist.md`](docs/order_checklist.md): the earlier hand-off list from routing to ordering (history).

## Opening the design

Clone with `git clone --recursive`, or run `git submodule update --init` after cloning, to get `tools/jlc`.

Open `hardware/control_card.kicad_pro` in KiCad 10. The project's own symbol and footprint libraries are set up in
`hardware/sym-lib-table` and `hardware/fp-lib-table`. Everything else comes from KiCad's standard libraries.

## Fabrication outputs

```sh
KICAD_ROOT=<unpacked KiCad AppImage (squashfs-root)> tools/fab_outputs.sh
```

This writes `hardware/fab/`:
- Gerbers and drill files, zipped;
- the JLCPCB BOM and placement files;
- a DRC report.

The headers J1 and J2 are left out of the assembly files, because they are soldered by hand. The FPGA has no JLCPCB
part number, so order it through JLCPCB's Global Sourcing or supply it yourself. Global Sourcing parts can only be used
in an assembly order once they have arrived in JLC's warehouse (Parts Manager → My Parts Lib).

Check stock right before ordering: judge each part by JLC's orderable quantity and minimum purchase, not the plain stock
count (see the production checklist, section 5):

```sh
python3 -I tools/jlc/stock_check.py hardware/fab/bom_jlcpcb.csv --boards 10
```

## FPGA pin assignment

`reference/pin_assignment.csv` lists every used FPGA ball with its signal, bank, direction and pin function, generated
from the schematic netlist. Quartus settings:
- banks 6C and 6D: 1.8-V LVCMOS;
- other banks: 3.3-V LVCMOS;
- configuration scheme: Active Serial x4;
- `DEVICE_INITIALIZATION_CLOCK OSC_CLK_1_100MHZ`;
- `ACTIVE_SERIAL_CLOCK AS_FREQ_100MHZ`.

## Generator scripts

The initial schematic and board came from the scripts in `tools/`:
- `gen_schematic.py` writes the schematic;
- `build_pcb.sh` builds the board: placement, FPGA pin assignment, power copper and routing.

The design has since been edited by hand in KiCad, so **don't rerun `gen_schematic.py` or `build_pcb.sh` on this
version**: they would overwrite the hand edits, pin swaps and routing. They stay in the repository as a record of how
the design was made.

## License

[MIT](LICENSE).
