# Control card: Agilex 3 replacement for U25

A KiCad 10 rebuild of the Proteus `u25_v2` Cyclone 10 control card. The FPGA becomes an Agilex 3 A3CZ065BB18AE7S (B18A package; until 2026-10-16 the A3CY025BB18AI6S).

## Fixed constraints

- **Outline and connectors:** the same outline as U25 and the ECP5 card, 32.538 × 33.8 mm. J1 (2×25 right-angle header, 1.27 mm pitch, top side, pins pointing off the edge) and J2 (1×5 JTAG header, 2.54 mm pitch) are at exactly the U25 positions. `tools/make_board.py` creates these. The aux origin sits on the old Gerber origin, so exported coordinates match the Proteus files.
- **Header mating:** J1 plugs directly into J2 on the tube_power_5_1 power board. The pin numbering is mirrored: card odd pin n mates with power board pin n+1, and card even pin n with pin n−1. `reference/power_board_header.csv` lists the signal on every pin. The power board uses 17 outputs and 3 inputs, all 3.3 V logic.
- **Layers:** 6 at JLCPCB, which includes free via-in-pad (filled and capped). That makes the 0.65 mm-pitch BGA fan-out and decoupling under the BGA much easier on this small board. 4 layers remains a fallback; the ECP5 card was 4 layers with 0.32 mm prepreg / 0.772 mm core.
- **Parts:** must be orderable from JLCPCB assembly. Regulators come from the Diodes AP61xxx family the user has used before.
- **JTAG:** J2 goes to an FTDI mini-module over flying leads, so its pin order is free. Choose whatever routes best.

## Architecture

- **I/O:** user I/O on 3.3 V HVIO banks, with no level shifters. That covers the header, 2 RGB LEDs, 4051 mux selects and both ADS7056 SPIs (DVDD 3.3 V, as on U25). Banks 6C and 6D are the exception: they run at 1.8 V. 6D carries the HyperRAM (moved from 6C on 2026-10-22, for easier length matching) and the clock; 6C is unused. Its VCCIO balls U17/W15, the HyperRAM and the oscillator are on `+1V8_HR`, from a TLV75518 fed by +3V3 (2026-10-17). Altera's power sharing table wants VCCIO_HVIO on its own regulator in power group 2B, not on the VCCPT/VCCIO_SDM rail.
- **Clock:** one 100 MHz 1.8 V oscillator (2026-10-16) drives PLLREFCLK1 (D18, bank 6D) and, on the same net `CLK100M`, the SDM's OSC_CLK_1 (BB44), so Quartus can set the configuration clock to OSC_CLK_1 100 MHz (faster configuration and AS_CLK; needed if a design ever uses transceivers, EMIF, MIPI or PHY Lite). The 33 Ω series resistor sits at the oscillator, with short branches to D18 and BB44. Bank 6D carries only the clock and runs at 1.8 V from `+1V8_HR` (2026-10-18). The clock first went to 6C's PLLREFCLK2 (B3), but B3 could not be routed: HyperRAM traces close it in on L1, and the 1.8 V buck sits under it on L6. HR_RESET_N stays on C2. The oscillator runs from `+1V8_HR`; the first 512 KB of the bitstream always loads on the internal oscillator.
- **HyperRAM:** 32 MB, 1.8 V W958D8NBYA5I (2026-10-15; it replaced the 8 MB 3 V IS66WVH8M8BLL because no 3 V part of 32 MB or more is stocked). Still to check: the HVIO speed limit against the HyperRAM clock.
  - **64 MB option:** W959D8NFYA5I is a drop-in. Its ball map, package and 1.8 V supply match the W958D8NBYA (both datasheets A01-003). It stacks two 256 Mb dies, so the HyperRAM controller must leave CR0[3] (fixed latency) at its default of 1 in both dies. JLC has none in stock; DigiKey had 478.
  - **Backups** (DigiKey, 2026-10-15): W958D8NBYA5I 945 on tray plus 1505 on reel; the 64 MB W959D8NFYA5I, 478; Infineon S80KS2562GABH*020 (32 MB HyperBus), 268–636 per grade. Avoid the S80KS..3 parts: they are octal xSPI, not HyperBus.
- **Analog:** 2 × (4051 mux → OPA365 buffer → ADS7056), on +3V3A from a TLV75533. **One ground (GND)**: U25's separate GNDA and its net tie are gone. Solid GND planes on L2/L5, with the analog parts grouped at the left edge, keep analog and digital apart.
- **ADC front end for 2.5 MSPS** (ADS7056 datasheet SBAS769, 2026-10-16): the 2.5 MSPS cycle is 400 ns = 18 SCLK at 60 MHz (300 ns) + tACQ 95 ns, so SCLK must run at 60 MHz.
  - Kickback RC: 33 Ω + 680 pF C0G at AINP (the datasheet's 2.5 MSPS design); corner 7.1 MHz, so the buffer needs UGB ≥ 4/(2πRC) = 28 MHz. The OPA365 has 50 MHz. The old 10 Ω / 330 pF needed about 190 MHz.
  - AVDD is the reference: 4.7 µF 0603 X5R (about 3.3 µF at 3.3 V; the datasheet asks for 3.3 µF) plus 100 nF, at the pin with no via in between.
  - CS/SCLK/SDO series resistors 33 Ω (were 100 Ω from U25): SDO is valid at most 10 ns after the SCLK rising edge, so at 16.7 ns per bit an RC delay of 1.5 ns matters. Capture SDO with a PLL phase-shifted clock tuned to the round trip, not on the launching edge.
  - Layout: kickback RC and AVDD cap at the ADC pins, ADC GND pin straight to the plane, no digital line under or across AINP/BUF_OUT/MUX_OUT.
- **Power:** follows the sequencing proven on agilex3_control_card_v1. Each rail's power-good enables the next: 0.75 V → 1.8 V → 1.2 V and 3.3 V.

  | Rail | Feeds |
  |---|---|
  | 0.75 V | VCC, VCCP, VCCL_SDM, VCCH_SDM, VCC_HSSI, VCCPLLDIG_SDM, VCC_IO_SDM, VCCL_ADC_SDM |
  | 1.8 V | VCCPT, VCCPT_HVIO, VCCIO_SDM, VCCADC, VCCFUSEWR_SDM, VCCPLL_SDM |
  | 1.2 V | VCCIO_PIO_3A_T, VCCIO_PIO_SDM, VCCRCORE |
  | 3.3 V | VCCIO_HVIO_6A–6H |

  The core regulator is a small module with power-good and remote sense, sized with Altera's Power and Thermal Calculator. The v1 card's TDA38812 (12 A) is oversized. Modules with built-in inductors save board area.
- **Configuration:** AS ×4 from a 1.8 V QSPI flash on Altera's supported list (v1 used an unsupported W25Q64JW). Also MSEL straps, nCONFIG/nSTATUS 1k pull-ups to 1.8 V, a 2k resistor from RREF_SDM to ground, and JTAG shifted from the 3.3 V header to SDM 1.8 V through an SN74AXC4T774. The flash's dedicated RESET# (ball A4, internal pull-up) is wired to AS_nRST (SDM_IO15, ball BA51): the Agilex 3 configuration guide (847422, 3.2.7.1) only supports QSPI flash with SFDP and a dedicated reset pin, and requires the SDM to own that reset.

## FPGA library

- **Symbol:** `hardware/lib/agilex3.kicad_sym` is Rolf-Altera's A3CY025B-B18A, from the `Adding_Altera_Agilex_symbols` branch of gitlab.com/Rolf-Altera/kicad-symbols (upstream MR kicad-symbols!5565). I changed only the Footprint field. Rolf's A3CZ100B symbol matches every power and ground ball on agilex3_control_card_v1.
- **Missing balls:** the A3C025 symbol has 433 pins, so 41 balls have no pin. 31 of them are also missing from the A3C100 symbol. The other 10 do exist on the A3C100: AH38 and AL41 (VCC_HSSI_L1), AT41 and AW41 (VCCPT_HVIO), and AW25, P38, P41, U36, U38, W44 (GND). Altera's pin-out file (`reference/A3CY025B_pin_list_B18A.csv`, version 2025-08-04, B18A Final) marks all 41 as NC or DNU, so they stay unconnected. The symbol matches the official list ball for ball.
- **A3CZ065BB18AE7S** (2026-10-16): 65 k LEs, Z spec (no HPS, crypto, EMIF, MIPI, PUF or SPDM; none used here), extended temperature grade, speed grade −7. Its B18A pin list (`reference/A3CZ065B_pin_list_B18A.csv`, 2025-08-04, Final) matches the A3CY025B list on all 474 balls (bank, function, NC/DNU), so the 025 symbol, footprint and pin assignment carry over unchanged. Speed grade −7: with OSC_CLK_1 the configuration network runs at 200 MHz and AS_CLK is limited to 25, 50 or 100 MHz (we use 100 MHz). Check core current (+0V75) for the larger die in the Power and Thermal Calculator. DigiKey 2026-10-16: $78.40, 84 in stock.
- **Altera schematic review** (Agilex 3 Schematic Review Worksheet v1.1, checked 2026-10-16; the AXC3000/TEI0131 schematic as a reference):
  - VCCPLLDIG_SDM (BB30), VCCPLL_SDM (BB38), VCCADC (AT36) and VCCRCORE (AB38, AE38) each get their own net behind a BLM18PG121SN1D bead (120 Ω at 100 MHz, JLC basic) with 47 µF 0603 + 1 µF 0201: `+0V75_PLLDIG`, `+1V8_PLL`, `+1V8_ADC`, `+1V2_RCORE`. The worksheet requires "proper isolation filtering" for the first three; the AXC3000 also filters VCCRCORE. The oscillator gets the same bead with 470 nF (`+1V8_OSC`), as on the AXC3000.
  - Ball-pair decoupling under the BGA is now 1 µF and 4.7 µF 0201 (was 100 nF), following the worksheet's per-rail values: 4.7 µF on VCC/VCCP, VCCPT and VCCIO_PIO; 1 µF on the SDM rails and VCCIO_HVIO.
  - nCONFIG and nSTATUS pull-ups are 10 kΩ (the worksheet value; were 1 kΩ).
  - Checked OK: VCCL_SDM 0.75 V for −7S, the rail sharing (VCCH_SDM to VCCL_SDM, VCCIO_PIO_SDM to VCCRCORE's 1.2 V), MSEL 011 (AS normal), RREF 2 kΩ 1 %, OSC_CLK_1 at 100 MHz, ADC reference and sensor pins to GND, temperature diodes and DNU/NC open, power-up order 0.75 → 1.8 → 3.3/1.2 V.
- **Footprint:** `hardware/lib/control_card.pretty/Altera_B18A` is built by `tools/make_bga_footprint.py` from Altera's ball table (`reference/altera-pbc-b18a-a5e-a3c-1p1.csv`, via Rolf-Altera/kicad-library-tools). It matches the v1 board's 474 balls within 0.034 mm and is not mirrored. Pads copy v1: 0.30 mm copper (not mask-defined), 0.35 mm mask opening, 0.30 mm paste. Smallest ball spacing is 0.65 mm.

## Lessons from agilex3_control_card_v1

From `reference/agilex3_card_v1_fpga_balls.csv` (its IPC-356 netlist) and the symbol pin names:
- **RX (A19) is on HSIO bank 3A_T, a 1.2 V bank**, but receives a 3.3 V UART signal. That's an overvoltage on the pin.
- **CLK32MHZ (AK2) is on HVIO 6G at 3.3 V**, but the oscillator runs at 1.8 V, below the 3.3 V logic-high threshold.
- **ADS7056 SPI (D18, F18, H21) is on HVIO 6D at 3.3 V.** If the ADC's DVDD was 1.8 V (as on the Ti60 card), the levels don't match.
- **13 nets end at the FPGA and go nowhere else**, on banks 6E and 6F (BH7, BH10, BJ2, BL2, BM2, BM3, BM8, BM9, BN5, BN8, BN11, BN14, BN16). The Ti60 names were carried over without being routed.
- **A3CY025 bank resources:** 8 HVIO banks × 20 pins (6A–6H), plus 48 HSIO in bank 3A_T. This card needs about 66 user I/O at 3.3 V, all on HVIO; HSIO stays unused.

## Parts (JLCPCB stock checked 2026-10-12 with `tools/jlc_search.py`)

| Function | Part | LCSC | Stock | Note |
|---|---|---|---|---|
| 0.75 V core buck | AP61302Z6-7 (3 A, PG) | C3193204 | 730 | 0.6 V FB; the AP61300 has no PG |
| 1.8 V, 3.3 V bucks | AP61102Z6-7 (1 A, PG) | C5224055 | 1018 | Use the AP61302 instead if 1 A is too little. AP61202 has only 72 in stock |
| 1.2 V (VCCIO_PIO, VCCRCORE) | TLV75512PDBVR | C2877864 | 2965 | from 3.3 V, enabled with it |
| Analog supply | TLV75533PDBVR (3.3 V) | C404027 | 132909 | 3.3 V chosen (U25 used a 3.0 V TPS73030) |
| Clock | OT3225100MJBA4SL 100 MHz, 1.8–3.3 V, 3225 | C4353707 | 2466 | on +1V8; 1.8 V needed for OSC_CLK_1. 25 MHz twin OT322525MJBA4SL (C669088, 45726) also fits |
| HyperRAM | W958D8NBYA5I (256 Mb, 1.8 V, 200 MHz) | C7420405 | 1107 | same 24-ball HyperBus ball map as before; bank 6C at 1.8 V |
| HyperRAM, 64 MB option | W959D8NFYA5I (512 Mb, 1.8 V, 200 MHz) | C19273217 | 0 (DigiKey 478) | drop-in: identical ball map and 6×8 mm package (datasheet A01-003). Two 256 Mb dies; the controller must keep CR0[3] = 1 (fixed latency, the default) in both |
| Config flash | MT25QU256ABA8E12-1SIT (1.8 V, TPBGA-24) | C2061023 | 48 | same part as on the user's Trenz Agilex 3 board; BGA chosen because it routes more easily. Footprint `BGA-24_6x8mm_Layout5x5_P1.0mm_CY0.5` (stock pads, 0.5 mm courtyard to fit the strip above the FPGA) |
| JTAG 3.3 → 1.8 V | SN74AVC4T774RSVR | C779392 | 109896 | same RSV pinout as the SN74AXC4T774RSVR, which JLC had 0 of on 2026-10-16; −40 to 85 °C |
| ADC | ADS7056IRUGR | C2669798 | 61 | low stock |
| Mux | SN74LV4051APWR (TSSOP-16) | C7793 | 3737 | |
| Buffer | OPA365AIDBVR | C96626 | 8412 | 50 MHz, 25 V/µs, zero-crossover rail-to-rail input; replaced the 10 MHz TLV316 (2026-10-16) so a full-scale channel step settles about 3× faster. Same SOT-23-5 pinout |

AP61102 pinout confirmed from the AP61100/AP61102 datasheet: 1 FB, 2 GND, 3 VIN, 4 SW, 5 EN, 6 PG (same as the AP61202/AP61302 in KiCad's library). The RGB LEDs are U25's Kingbright APFA3010LSEEZGKQBKC (C5393554, 2006 at JLC on 2026-10-15). It is a 3.0 × 1.5 × 1.0 mm right-angle (side-view) common-anode part rated at 2 mA: pin 2 is the anode, and 1/3/4 are the red/green/blue cathodes. Its footprint `LED_RGB_APFA3010_RightAngle` (`tools/make_led_footprint.py`) follows the datasheet land pattern, with the lens toward −y. The pinout and the side the lens faces were read from the datasheet drawings; U25's Gerbers show the same pad shapes, with the rear pads toward the board interior.

## Schematic (first draft, generated)

`tools/gen_schematic.py` writes everything:
- the root sheet `hardware/control_card.kicad_sch` and 7 sub-sheets in `hardware/sheets/` (power, FPGA power, configuration, FPGA I/O, HyperRAM/clock, ADC, header/LEDs)
- `hardware/lib/control_card.kicad_sym`
- `reference/pin_assignment.csv`
- `reference/bom_draft.csv`

`tools/jlc_bom.py` looks up every MPN at JLCPCB and caches the results in `reference/jlc_parts.csv`; the generator fills the LCSC field from that file.

Run it (bash; `$K` is the unpacked KiCad AppImage):

    KICAD_SYMBOL_DIR=$K/usr/share/kicad/symbols KICAD_CLI="<kicad-cli>" python3 -I tools/gen_schematic.py

Style: every pin gets a short stub and a net label. Nets used on more than one sheet get global labels. Unused pins get no-connect flags.

**Rerunning the generator overwrites the sheets.** Once a sheet has been edited in KiCad, edit it there instead.

Checks done:
- ERC: 0 violations.
- Netlist: no named net with only one connection. Every power-board signal reaches its FPGA ball.
- Footprints: every referenced footprint exists.
- BOM: every part except J1, J2 and the FPGA has an LCSC number.

To bring the parts into the PCB: Tools → Update PCB from Schematic, with "Re-link footprints to schematic symbols based on their reference designators" ticked, so the pre-placed J1 and J2 are reused.

Review before layout:
- Decoupling values and counts on the FPGA power sheet are a first pass. Check them against Altera's PDN tool.
- ADS7056 footprint: `Texas_UQFN-8_1.5x1.5mm_P0.5mm`. Check it against the RUG0008A land pattern.
- HyperRAM CK# (B1) is left unconnected: the W958D8NBYA defaults to a single-ended clock (CR1[6] = 1), and its datasheet says CK# is then not used. RESET# has an internal pull-up; R24 (10k to +1V8) stays.
- Core sense: the 49.9k/200k divider sits on VCCLSENSE/GNDSENSE, with 100R/10R local fallbacks to +0V75 and GND.
- JTAG J2 pin order: TCK, TDI, TMS, TDO, GND. Change it freely for routing.

## Placement (first pass, generated)

`tools/build_pcb.sh` (set `KICAD_ROOT` to the unpacked AppImage) runs the whole chain:
1. regenerate the schematic and look up parts at JLCPCB
2. export the netlist
3. build a fresh board (`make_board.py`)
4. sync footprints and nets (`sync_pcb.py`)
5. place the parts (`place.py`)

DRC's schematic-parity check then reports 0 differences.

**Reproducible builds:** KiCad writes footprints in UUID order, and the placement and copper scripts take parts in board order. Fresh UUIDs on every build used to reshuffle interchangeable parts (identical caps, the two ADC chains), which changed the placement and the copper. `make_board.py` and `sync_pcb.py` now give every footprint the UUID recorded in `reference/footprint_uuids.csv` (`tools/fp_uuid.py`), taken from the approved board at commit cc7c338; references not listed get a UUID derived from their name. A rebuild reproduces that board's placement and copper exactly.

**It overwrites `hardware/control_card.kicad_pcb`.** Once routing starts, place and route by hand in KiCad and stop running it.

`place.py` groups parts by the `Group` field each symbol gets from the generator. It works in two passes:
1. ICs, inductors and the BGA decoupling are packed into each group's region.
2. Other 2-pin parts go next to the pad they connect to: series resistors at the ADC pins, LED resistors at the LEDs, decoupling at its chip's supply pin.

The bottom under the BGA (x 83–101, y 104–122) is kept out for everything except BGA decoupling. No courtyards overlap.

| Side | Area | Contents |
|---|---|---|
| Top | upper strip | two side-view RGB LEDs D1/D2 on the north edge, lens out (x 77.5 and 81.8, end pads 1.8 mm from the edge as on U25; three no longer fit), then HyperRAM (next to banks 6C/6D) and the QSPI flash pushed against it (next to the SDM); both BGA-24 with a 0.5 mm courtyard. The memory strip moved 0.4 mm east (2026-10-15) so its courtyards clear D2's; its routes were ripped up and re-routed with `ROUTE_ONLY` (route_signals.py, route_vias.py) |
| Top | left column | ADC chain A, mux at the bottom next to J1's analog pins, turned so its COM output (pin 3) faces the buffer's + input |
| Top | right column (below J2) | 3.3 V buck cell, laid out in rows; below it, hand-placed next to the SDM balls they serve: the MSEL1 pull-up, the MSEL2 pull-down (and its DNP pull-up option), the nCONFIG and nSTATUS pull-ups, and the RREF_SDM resistor |
| Bottom | upper-left, partly under the FPGA's west edge | 1.8 V buck cell, placed by hand (`MANUAL` in `place.py`, kept across rebuilds), next to the analog LDO, since both take 5 V from the run to the left side |
| Bottom | upper strip | the 100 MHz oscillator; HyperRAM and flash decoupling, each 0402 with its pads on that BGA's VCC/VSS ball pair; configuration pull-ups. The HyperRAM routes entirely on L1, so the rest of this strip on L6 stays free |
| Bottom | left column | ADC chain B (mux next to J1, COM output facing the buffer), analog LDO |
| Bottom | under the FPGA | 23 × 100 nF 0201 on supply/GND ball pairs; bulk 0603 in the via-free channels; the JTAG level shifter (UQFN-16) with 0201 pull-ups and decoupling, hand-placed under the FPGA's north edge (about 8 mm from the JTAG balls) to keep the SDM corner free; clear of every via |
| Bottom | right column | core buck, 1.2 V LDO |

**Via model:** only supply, ground and sense balls get a via-in-pad; every signal I/O escapes on L1 (59 of the 66 assigned signals are on the outer two rings). Unused I/O, NC and DNU balls (about 180) have none, so the area under the unused HSIO bank is free for parts. Since the pin assignment decides which balls need vias, `build_pcb.sh` places, assigns pins, then places again.

Design rules for JLCPCB 6-layer: 0.1 mm clearance, 0.09 mm minimum track, 0.2/0.35 mm vias. The SOT-563 regulators need the 0.1 mm clearance, since their pads are 0.15 mm apart.

Before routing:
- **BGA decoupling:** the 0201s already sit on supply/GND ball pairs, with pads on the vias. Supply/GND neighbours are 0.75 mm apart; the stock 0201 pads (±0.32 mm, 0.46 mm long) cover a via at ±0.375 mm. The ball map holds 8/7/6/2 of them on 0.75/1.8/3.3/1.2 V; that sets the counts. Bulk 0603s use the variable-pitch package's via-free channels, which takes some bottom-layer channel space; escape routing goes on the inner layers.
- **GND balls under the 1.8 V cell** (no via-in-pad possible there):
  - A3, A5, C1 are on the outermost ring: connect outward on L1. C1 can also join E1, 0.65 mm away.
  - B2 is on the second ring: join A3/A5 on L1 and go out with them.
  - H3: L1 link to L2, 1.07 mm away, which has a free via.
  - D7: L1 link to B9, 1.33 mm away, which has a free via; this crosses the outer-ring escape, so route it with care.
  - T4 is cleared by moving C4 0.1 mm.
- **Silkscreen:** about 430 DRC warnings are reference text overlapping. Move or hide the references (keep them on F.Fab/B.Fab) during layout.
- **L2:** its courtyard sits 0.04 mm inside the 0.3 mm edge keep-out; its copper is well inside the board.

## Power distribution plan (agreed 2026-10-12)

Stackup: JLC 6-layer 2313 build, assumed 1.6 mm. From top to bottom (dielectric between each copper layer in brackets): L1 (0.1 mm) L2 (0.565 mm core) L3 (0.127 mm) L4 (0.565 mm core) L5 (0.1 mm) L6. Verify with JLC's impedance calculator. Inner copper 0.5 oz, which is fine for L4.

| Layer | Use |
|---|---|
| L1 | components, BGA outer-ring escape, J1 fan-out, local pours for the top bucks and 5 V |
| L2 | solid GND |
| L3 | signals (inner-ring escape, SPI) plus a +1V8 pour under the FPGA power block; +1V2 as 0.25–0.3 mm traces |
| L4 | +0V75 island under the core ball block, extended east to the core buck's output caps (x 102.3); +3V3 fills the rest of the board and is open for signal routing |
| L5 | solid GND |
| L6 | components, BGA decoupling, local pours (core buck output, 5 V) |

The FPGA's supply balls all sit in a central block, about x −3.4…4.1, y −3.5…5.0 mm from the package centre:
- 3.3 V: two west columns
- 1.8 V: one column, plus balls scattered in the core
- 0.75 V: core, centre-right
- 1.2 V: top edge and an east column

0.75 V and 1.8 V are interleaved in the core, so they need separate layers. The outer rings are signals and GND only.

1.8 V: the buck is bottom-left. Run +1V8 along the bottom upper strip (L6, free because the HyperRAM routes on L1), then drop into the L3 pour from the north of the power block. That keeps it out of the west-side escape. Branches go to the flash and the JTAG shifter.

Core sense: VCCLSENSE/GNDSENSE run as a coupled pair on L6 to R1/R2, away from the switch node. 5 V runs to the left side (1.8 V buck and analog LDO) as a 0.4–0.5 mm trace or pour, since it now carries the 1.8 V buck's input current.

**Implemented** (`tools/setup_board.py`, `tools/power_pours.py`, both run by `build_pcb.sh`):
- **Stackup:** as above, total 1.608 mm, ENIG. Layer roles: In1 `L2.GND` (power), In2 `L3.SIG_1V8_1V2` (signal), In3 `L4.0V75_3V3` (power), In4 `L5.GND` (power). Vias are filled and capped.
- **Net classes:**

  | Class | Nets | Track | Vias |
  |---|---|---|---|
  | PWR_CORE | +0V75 | 0.5 mm | 0.45/0.25 mm |
  | PWR | +5V, +3V3, +1V8, +1V2, +3V3A | 0.3 mm | 0.45/0.25 mm |
  | GND | GND | 0.3 mm | 0.45/0.25 mm |
  | SW | /Power/SW_* | 0.5 mm, 0.15 mm clearance | |
  | SENSE | VCC_SENSE_P, VCC_SENSE_N | 0.15 mm | |
  | Default | everything else | 0.1 mm, 0.1 mm clearance | 0.35/0.2 mm |

- **Sense pair as a differential pair:** the FPGA's GNDSENSE net is named VCC_SENSE_N, so KiCad's router treats VCC_SENSE_P/VCC_SENSE_N as a differential pair. In the SENSE class the pair width is 0.15 mm, the gap 0.15 mm and the via gap 0.25 mm. It only carries DC feedback, so the custom rule `sense_pair_loose` in `hardware/control_card.kicad_dru` (written by `setup_board.py`) keeps it easy to route: a gap of 0.1–5 mm, up to 100 mm uncoupled, and up to 50 mm skew.

- **Via-in-pad:** 200 vias, 0.25/0.15 mm, on every supply, ground and sense ball of the FPGA, HyperRAM and flash. The 6 FPGA GND balls under the 1.8 V cell are skipped; they connect on L1.
- **Zones:**
  - L2 and L5: GND, whole board.
  - L3: +1V8 (west half and power block, a north arm under the flash and JTAG shifter, a notch north of the BGA covering the 1.8 V HyperRAM, and a band at y 119–123 reaching the SDM pull-ups at the right edge), with a +1V2 island at higher priority (north edge and east column of the block, east to U5). The L3 strip south of y 123 is kept for the 5 V run to the left side.
  - L4: +0V75 island (core ball block, extended east to x 102.3 over y 109.3–118.6), with +3V3 filling the rest. Since 2026-10-16 both east buck cells face the FPGA (`-|`: inductor east-west with its output pad west, first output cap north-south beside it, regulator and input cap on the far side), so the island reaches the core output caps without running under the switcher or inductor. It replaced a strip that ran east under the whole core cell to x 107.4.
- DRC refills the zones with no clearance errors or shorts.

- **Tap vias** (`tools/tap_vias.py`, 112 vias at 0.3/0.15 mm): every SMD power/GND pad gets a via to its plane, provided the plane really exists at that spot (zone outline and priority checked).
  - Pads at least 0.45 mm across get the via in the pad.
  - Smaller pads (0201, SOT-563, TSSOP) get the nearest free spot plus a stub.
  - Large +0V75 pads get two vias.
  - Each via keeps pad clearance (0.15 mm to switch nodes) and 0.2 mm hole clearance from all other-net copper, including the FPGA's top-side balls.
  - DRC is clean apart from silkscreen.

- **Regulator cell copper** (`tools/cell_copper.py`). The build runs it before the taps, so the critical copper is laid first and the vias go around it.
  - **Layout:** the core and 3.3 V bucks are row cells. The inductor's SW pad is the upper pad, aligned with the IC's SW pin, so the SW link is a short straight track and the output pad faces the output caps. The core buck sits on the bottom, where its VIN pin is at the top of the package, so its input cap goes in a row above the IC. On the hand-placed 1.8 V cell the inductor is turned 180° for the same reason.
  - **Routing:** each cell net except GND is connected with a minimum spanning tree of tracks, widest nets first. Widths: SW 0.6, +0V75 0.8, +5V/+1V8 0.6, +3V3 0.5, +1V2/+3V3A 0.4, small signals 0.15 mm. Tracks leave small pads through a 0.35 mm neck at pad width. Paths tried: straight, L, then Z detours. Clearance is net-class, plus 0.2 mm to other-net drill holes.
  - **GND pour:** each buck cell gets a GND zone on its own layer.
  - **Leftover pass:** after the taps, any untapped plane-net pad is routed to the nearest same-net via or pad.

- **Trace-routed rails** (`tools/route_rails.py`, after the leftover pass): one grid router, one rail at a time; each rail's copper is an obstacle for the next. Order: the 3.3 V feedback node, the core sense pair, the FPGA GND balls under the 1.8 V cell, the core power-good link, +5V, the 1.8 V power-good link, +3V3A, then the plane-net leftovers. The pins with the fewest exits go first. The step and origin of the routing grid can be set per rail. Tracks are never routed between the two pads of a 2-pad part.
  - **Via keep-out at fine-pitch ICs:** vias of other nets stay 0.3 mm further from the pads of fine-pitch ICs (SOT-563, QFN), so their pins keep a way out. A +5V via had once sealed the 3.3 V buck's EN pin.
  - **Plane mode:** used for the plane-net leftovers and the GND balls. Copper that already has a via, a THT pad or a same-net pour counts as connected. Every other piece is routed to it, or ends in a new via where the net's plane really exists (zone outline and priority checked, as in `tap_vias.py`).
  - **Reproducible:** pieces are picked in sorted cell order, because Python's set order of the grid cells changes between runs. Two builds give identical copper.
- **5 V runs.** A grid router (0.1 mm, Dijkstra) over F.Cu, L3 and B.Cu grows a tree from J1 pin 1. Each round it joins the nearest unconnected piece of +5V copper: the three buck cells, R5, R8, C14–C16 and the analog LDO.
  - **Widths:** 0.6 mm on the outer layers, 0.8 mm on L3 (0.5 oz copper). Where the full width does not fit, a 0.3 mm neck is used at three times the cost; this happens around the J1 pin 1 exit and the via fields.
  - **Layer preference:** L3 costs 1, B.Cu 2 and F.Cu 5 per mm, so the long runs use the reserved L3 strip and L1 stays free for the FPGA I/O.
  - **L3 limits:** L3 is used only outside the +1V8/+1V2 pours, i.e. the south strip below y 123 and the west edge.
  - **Vias:** 0.45/0.25 mm, cost 2 mm each.
  - **Clearances:** net class plus a 0.03 mm grid margin; 0.2 mm to drill holes.
  - **Overrides:** existing +5V copper lifts the blocking only where the new track would stay inside it.
  - **Result:** B.Cu along the right edge from J1 pin 1; L3 west along the south strip and up the west edge to the 1.8 V cell and the analog LDO; an L3 branch up the right side to the core cell; a short F.Cu stub to the 3.3 V cell input C8.
- **Core sense pair** (VCC_SENSE_P, VCC_SENSE_N): routed on L6 from the FPGA's VCCLSENSE (AH33) and GNDSENSE (AL33) via-in-pads to the core divider.
  - **Widths and clearance:** 0.15 mm tracks, with 0.1 mm necks between the ball vias. The pair keeps 0.5 mm extra clearance from the switch node.
  - **Grid:** the sense pair uses a 0.05 mm grid aligned to the ball-row midlines. Between the 0.75 × 0.77 mm pitch via-in-pads, a track centre only has a 0.04–0.06 mm window, which the 0.1 mm grid missed.
  - **Topology:**
    - The P ball is north of the N ball, and `place.py` stacks the divider the same way, so the pair needs no crossing and stays entirely on L6.
    - VCC_SENSE_P goes first and lands on R1's west pad and the fallback R3 hung under it.
    - VCC_SENSE_N follows on the south side to R2's west pad and the fallback R4 under it.
    - Apart from the two ball via-in-pads, the pair has no vias.
    - Inside the BGA the two lines take separate channels through the via field; from the BGA edge to the divider they run side by side.
- **Buck control links** (0.15–0.2 mm, F.Cu/B.Cu, 0.3/0.15 mm vias):
  - **FB_3V3** (the 3.3 V feedback node) joins the divider around R9's +3V3 pad, 0.3 mm extra from the switch node.
  - **PG_0V75** (core PG → 1.8 V EN) and **PG_1V8** (1.8 V PG → 3.3 V EN) cross under the BGA. They use the sense pair's 0.05 mm ball-midline grid and prefer L6.
  - **No extra switch-node clearance on the PG links:** each EN pin sits 0.5 mm from its buck's SW pin, so a keep-away would seal it in.
  - **Order:** the PG links are routed after the sense pair, so they go round the divider instead of enclosing it. The core link also goes before +5V. Otherwise 5 V's way to R5 closes the cell's only exit south.
  - **PG_0V75 route:** from U2.6 down past R5, between the FB column and the output caps, under R4, then west under the BGA.
  - **Crossing:** the two links are crossed. U3.5 is above U3.6, but U2 is south of U4, so PG_1V8 changes layer.
- **FPGA GND balls under the 1.8 V cell** (A3, A5, B2, C1, D7, H3, R1; no via-in-pad there): linked on L1 to a GND ball with a via. They use a 0.05 mm grid on the 0.65 mm-pitch corner's midlines.
- **Plane-net leftovers:** pads the tap pass could not give a via (C50 +1V8, R3.1 +0V75, C44/C46 +1V2, a +3V3 piece of the 3.3 V cell) are routed to plane-connected copper or to a new via.
- **Analog supplies:** these stay on the outer layers, over the L2/L5 GND planes and away from the digital supplies on L3/L4. Vias are 0.3/0.15 mm, and their vias also keep clear of L3 tracks.
  - **One analog net:** the U25 design filtered each chain's AVDD through a 22 uH bead (AVDD_A/AVDD_B). The beads were dropped (2026-10-14), so the muxes, buffers and ADC AVDD all sit on +3V3A from the TLV755 LDO, with local 100n + 1u caps at each buffer/ADC.
  - **+3V3A** (0.4 mm): from LDO U6.5 to both chains.
- **ADC orientation:** both ADS7056 turn so their digital side (CS/SDO/SCLK, pins 1-3) faces north toward the FPGA (`FACE_NORTH` in `place.py`).

**Power routing is complete:** every supply, ground, sense and control net is connected, and copper DRC is clean. The remaining DRC unconnected items are signal nets.

**Buck cell small parts** have dedicated row slots in `place.py` (roles FB, PG, SNSP, SNSG). Each FB-role part turns its FB pad toward the regulator's FB pin, and the input/output caps turn their supply pad toward VIN and the inductor output.
- **3.3 V cell:** the input, output and feed-forward caps stand in one row and the divider sits below. The FB trunk runs from U4.1 down the copper corridor between the BGA's east balls and U4's left pins.
- **Core cell:** the divider is stacked to match the remote sense pair, which arrives on L6 from the FPGA in the west with P north of N.
  - **Divider:** the top resistor R1 (on VCC_SENSE_P) sits above the bottom resistor R2 (on VCC_SENSE_N). Their sense pads face the FPGA's sense balls (orientation rule SENSE>U1), so the FB pads are on the east. The FB node runs from U2.1 diagonally to R1 and straight down to R2.
  - **Fallbacks:** the sense fallbacks hang vertically under the sense pads (`HANG`): R3 in the gap between the divider rows, R4 below R2. Their +0V75/GND pads take a via-in-pad to the plane; `cell_copper.py` leaves those pads to the tap pass.
  - **PG pull-up:** R5 turns its PG pad toward U2.6 (PG>U). An empty slot in the lower divider row keeps the output caps in their column and leaves the channel for the PG link.
  - **Output caps:** both stand under the inductor.

## FPGA pin assignment (placement-driven)

The FPGA's I/O can go on any 3.3 V HVIO ball, so pins follow the placement rather than the other way round.

`tools/assign_io.py` takes each signal's target pad from the placed board: J1 pin, ADC series resistor, HyperRAM ball, LED resistor, or oscillator series resistor. It assigns the 66 signals to the 160 HVIO balls with a minimum-cost matching. Cost is distance, plus 0.5 mm per mm of depth into the ball array.

Constraints:
- CLK100M on a PLLREFCLK ball, alone in bank 6D (1.8 V).
- All HyperRAM signals in one bank. Fixed to 6C (`HR_BANK`) by the generator; moved by hand to 6D on 2026-10-22, in the schematic only, for easier length matching (balls D10, D26, F7, F10, F13, F18 for HR_CK, F21, F26, F27, H7, H13, H21; `reference/pin_assignment.csv`). 6D runs at 1.8 V and also carries CLK100M. On the hand-routed board the LEDs moved out by hand: LED2_R C2→N2 and LED3_B F3→K3 (both in bank 6H); LED 3 was dropped later.
- Hand swaps after the matching (`BALL_SWAPS` in `assign_io.py`, same bank, applied in order): BM8↔BN8, BL51↔BM51, BM29↔BN29, BM42↔BN42, then BL51↔BM50. Each outer/inner ball pair now matches J1's odd/even rows, so those J1 links route on L1 without crossing.
  - BL51 and BM50 can each leave on top only to the west. East and south are closed by GND via-in-pads 0.65 mm apart (BL52/BM52 and BN50/BN51), where a 0.1 mm track needs 0.674 mm.
  - So BL51 takes CUK_CS (J1.7) on the outside, BM50 takes PRI_DHB_LO (J1.5) inside it, and BM51 takes PRI_DHB_HI (J1.3).
- V1→M2 (2026-10-14, the user's request during hand routing): ADCA_SCLK moves to the free bank-6H ball M2, which is closer to its series resistor R28. V1 is left unconnected.

The result goes to `reference/io_assignment.csv`. The generator uses it, and `reference/pin_assignment.csv` lists the final balls.

`build_pcb.sh` reruns it after placement; `--keep-io` keeps the current file. Once the board is routed, freeze the assignment, then build the Quartus pin constraints from `pin_assignment.csv`.

## ADC mux input assignment

The FPGA renumbers mux channels freely, so `tools/assign_mux.py` chooses which 4051 input takes which J1 analog signal. For each mux it tries every arrangement and keeps the one with the fewest crossings between the straight J1-pad → mux-pad lines, then the shortest total length. The leftover input is grounded as a zero reference.

Result (also the FPGA channel table, in `reference/mux_assignment.csv`):
- U10 (ADC A): X0=ADA2 X1=ADA3 X2=ADA4 X3=ADA1 X4=ADA6 X5=ADA0 X6=ADA5 X7=GND. 0 crossings; U25's mapping would give 9 here.
- U13 (ADC B): X0=ADB2 X1=ADB1 X2=ADB0 X3=ADB3 X4=GND X5=ADB6 X6=ADB4 X7=ADB5. 0 crossings.

`build_pcb.sh` reruns it after placement, with the pin assignment.

## Signal routing

**Pass 1: top copper, no vias** (`tools/route_signals.py`, run by `build_pcb.sh` after the rails). It routes every signal net whose pads are all on the top side or through-hole: 79 nets.
- **Grid:** 0.025 mm, A* with eight directions and a turn penalty, so paths are straight 45°/90° runs. The FPGA balls sit on mixed pitches down to 0.65 mm, where a 0.1 mm track between two balls leaves a 0.026 mm window for its centre. No coarser grid lines up with every channel.
- **Tracks:** 0.1 mm wide, with Default net-class clearance. Tracks are never routed between the two pads of a passive. Each net routes in a window around its pads: 3 mm first, then 8 mm.
- **Detour limit:** a connection may cost at most 1.5× its straight-line bound plus 3 mm. Longer detours, such as loops around half the board, wall off later nets. Those nets wait for the via pass instead.
- **Negotiated congestion (PathFinder):** the nets are routed in rounds. Each net may cross other signal nets at a cost that rises each round, and contested cells build up a history cost.
  - After 6 rounds, nets that still overlap are dropped, most conflicts first.
  - Each dropped net then gets one more try with all other routes as obstacles.
  - **Rip-up:** a net that still fails but routes on its own takes that path. The nets in its way are ripped up and rerouted after it. The change is kept only if they all route again. This is how PRI_DHB_LO gets out past CUK_CS.
  - The run takes about 10 minutes.
- **J1 footprint:** a project copy, `control_card:PinHeader_2x25_P1.27mm_Horizontal_U25`, with U25's 0.8128 mm pads on 0.5588 mm drills (0.032/0.022 in, from the U25 Gerbers). The stock 1.0/0.65 mm pads leave 0.27 mm between pins. These leave 0.46 mm, so a 0.1 mm track reaches J1's inner, even-numbered row between the outer-row pins with 0.18 mm clearance each side. The annular ring is 0.127 mm, as on U25.
- **Result:** 57 of the 79 nets are routed, and copper DRC is clean. With the stock J1 pads it was 46, and 55 before the ball swaps and rip-up.
- **Left for the via pass:**
  - The nets that cross another net or would need a detour over the limit.
  - `/ADC/AINP_A`, which is blocked by power copper even on its own.
  - The 42 nets with a pad on the bottom side.

**Pass 2: vias** (`tools/route_vias.py`, run by `build_pcb.sh` after pass 1). It routes every signal net still open on F.Cu and B.Cu: the pass-1 leftovers and the nets with a pad on the bottom, 64 nets.
- **Router:** the same grid router (0.025 mm, A* with turn penalty, detour limit, negotiation in 4 rounds, retry, rip-up), on two layers. A step to the other layer places a 0.3/0.15 mm via and costs as much as 1.5 mm of track.
- **Fixed obstacles:** all copper already on the board, the pass-1 tracks included. L3 isn't used for signals, because it is mostly the +1V8/+1V2 pour.
- **Via rules:** a via keeps net-class clearance from other nets' copper on every layer, including inner-layer tracks such as the 5 V run on L3.
- **Hole clearance:** the via's hole keeps 0.2 mm from other copper. With a 0.3/0.15 mm via that means 0.125 mm copper to copper, the stricter of the two rules.
- **Placement limits:** no via between a passive's pads, and none in an FPGA signal ball, because signals escape on L1.
- **Result:** 42 of the 64 nets are routed with 54 vias. Copper DRC is clean, and the run is reproducible.
- **Left (22 nets, 25 unconnected items):**
  - ADC chain A: ADCA_CS_N_R, ADCA_SCLK_R, ADCA_SDO_R, AINP_A, ADA5, ADA6, ADASEL0, ADCA_SCLK
  - ADC chain B: ADCB_SCLK_R, BUFB_OUT, ADB5, ADB6, ADCB_SDO
  - config: MSEL1, NCONFIG, NSTATUS, TDI
  - LEDs: LED1_G, LED1_R, LED2_B, LED2_R, LED3_B
- **Why they're left:** they're crowded in the left-side ADC column and around the config pull-ups. Some can't route at all past the existing copper. Others need detours of 18–38 mm with 3–6 vias.

## Open items

- Core current estimate (Altera Power and Thermal Calculator). Confirms AP61302 (3 A) for the core and AP61102 (1 A) for 1.8 V.
