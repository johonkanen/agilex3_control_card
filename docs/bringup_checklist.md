# Bring-up checklist: Agilex 3 control card (first JLCPCB build)

For whoever verifies the assembled boards, human or agent, starting with no prior context. Work through the sections in
order and stop at the first failure. Record every measurement in the log at the end (section 12), one column per board.

## 0. Context

- **The board:** an FPGA control card (Altera Agilex 3 **A3CZ065BB18AE7S**, B18A BGA) that plugs into a power-electronics
  board through J1. Design files are in `hardware/` (KiCad 10).
- **Read first:**
  - `README.md`;
  - `docs/agilex3_requirements.md` (rails, bank voltages, power-up order, configuration pins);
  - `reference/pin_assignment.csv` (every used FPGA ball);
  - `reference/power_board_header.csv` (J1 pinout and the mirrored mating with the power board).
- **Ordered:** JLCPCB, 6 layers, ENIG, both sides assembled. U1 came through Global Sourcing. **J1 (2×25 1.27 mm right
  angle) and J2 (1×5 2.54 mm) were not assembled:** they are soldered by hand.
- **Not on the board:** test points, a power LED, and a "configuration done" LED. Probe on component pads (the reference
  designators below). Find a part with KiCad's search (Ctrl+F in the PCB editor) or in `hardware/fab/cpl_jlcpcb.csv`
  (X/Y in mm).

### Key facts (from the schematic netlist)

| Item | Detail |
|---|---|
| Input | +5V on J1 pin 1. GND on J1 pins 2, 35, 36 and J2 pin 5 |
| J2 (JTAG, 3.3 V side) | 1 TCK, 2 TDI, 3 TMS, 4 TDO, 5 GND. No VREF pin: use a 3.3 V JTAG adapter. Level shifter U8 (SN74AVC4T774): 3.3 V header side to 1.8 V FPGA side |
| LEDs | D1 = LED1, D2 = LED2 (side-view RGB, north edge). Common anode on +3V3, cathodes through 100 Ω to the FPGA, so **active low**. LED1 R/G/B = balls N2/M2/N1; LED2 R/G/B = M1/L1/K3 |
| Clock | X1 100 MHz (1.8 V, from +1V8_OSC) → R25 33 Ω → net CLK100M → FPGA D18 (bank 6D PLLREFCLK1) and BB44 (SDM OSC_CLK_1) |
| Configuration | Active Serial x4 from U7 MT25QU256 (1.8 V QSPI). MSEL = 011 (AS normal) |
| HyperRAM | U9 W958D8NBYA5I (32 MB, 1.8 V) on bank 6D; data lines length-matched to 10.8 mm |
| ADCs | 2 channels, each mux (U10/U13 SN74LV4051A) → OPA365 (U11/U14) → ADS7056 (U12/U15), 14-bit, AVDD = +3V3A is the reference |

### Supply rails

| Rail | Source | Nominal | Probe on | Comes up |
|---|---|---|---|---|
| +5V | J1 pin 1 | 5.0 V | C15 pin 1 | input |
| +3V3A | U6 TLV75533 from +5V, always enabled | 3.30 V | U6 pin 5, C13 pin 1 | immediately with +5V |
| EN_0V75 | R46 100k from +5V, R47 200k to GND | 3.33 V (below VIN − 0.2 V: forced PWM) | R46 pin 2 | immediately with +5V |
| +0V75 (core) | U2 AP61302 buck, EN = EN_0V75 | 0.753 V (0.6 V × (1 + R1 51k / R2 200k)) | C2/C3 pin 1, L1 pad 2 | 1st |
| PG_0V75 | U2 pin 6, R5 100k to +5V, R48 200k to GND | → 3.33 V when the core rail is good | R5 pin 2 | after +0V75 |
| +1V8 | U3 AP61102 buck, EN = PG_0V75 | 1.800 V (0.6 × (1 + 200k/100k)) | C6 pin 1, L2 pad 2 | 2nd |
| PG_1V8 | U3 pin 6, R8 100k to +5V, R49 200k to GND | → 3.33 V | R8 pin 2 | after +1V8 |
| +3V3 | U4 AP61102 buck, EN = PG_1V8 | 3.31 V (0.6 × (1 + 200k/44.2k)) | C9 pin 1, L3 pad 2 | 3rd |
| PG_3V3 | U4 pin 6, R50 100k to +5V, R51 200k to GND | → 3.33 V | R50 pin 2 | after +3V3 |
| +1V2 | U17 AP61102 buck from +5V, EN = PG_3V3 | 1.200 V (0.6 × (1 + 200k/200k)) | C82/C11 pin 1, L4 pad 2 | 4th, with +1V8_HR |
| +1V8_HR (banks 6C/6D, HyperRAM, oscillator) | U18 AP61102 buck from +5V, EN = PG_3V3 | 1.800 V (0.6 × (1 + 200k/100k)) | C85/C75 pin 1, L5 pad 2 | 4th, with +1V2 |
| +0V75_PLLDIG | FB1 + C65/C66 from +0V75 | ≈0.75 V | FB1 pin 2 | with +0V75 |
| +1V8_PLL, +1V8_ADC | FB2, FB3 from +1V8 | ≈1.80 V | FB2 pin 2, FB3 pin 2 | with +1V8 |
| +1V2_RCORE | FB4 from +1V2 | ≈1.20 V | FB4 pin 2 | with +1V2 |
| +1V8_OSC | FB5 from +1V8_HR | ≈1.80 V | FB5 pin 2, C54 pin 1 | with +1V8_HR |

- **Core regulator sense:** the core regulator senses the voltage at the FPGA balls (VCC_SENSE_P at AH33, VCC_SENSE_N at
  AL33), through R1/R2 (51k/200k). C77 (100 pF C0G) across R1 is the feed-forward capacitor the AP61302 requires. R3 (100 Ω)
  and R4 (10 Ω) give a local fallback path if the sense lines are open.
- **Forced PWM:** every buck's EN sits at about 3.33 V, below VIN − 200 mV, which forces PWM at any load (AP61x0x
  datasheet, Enable section). EN above VIN − 200 mV would select PFM at light load. To compare the modes, remove the
  200k resistor to GND on that buck's enable net (R47, R48, R49 or R51; R51 switches both U17 and U18).
- **Tolerances:** use ±3 % as the screening limit. The exact Agilex 3 limits are in the Device Data Sheet (848370); check
  VCC/VCCP (0.75 V for −7S) against it before running heavy designs.

## 1. Incoming inspection (no power)

- [ ] **U1:** marking reads A3CZ065BB18AE7S. Pin-1 (A1 corner) mark at the upper-left in KiCad's top view, i.e. toward
  D1/D2 and the J2 side is right, J1 is at the bottom.
- [ ] **Orientation of polarized parts:** the JLC CPL used rotation corrections that weren't confirmed for every package.
  Pin 1 as seen from the side the part is on (KiCad top-view coordinates; bottom parts seen from below are mirrored
  left-right):

  | Ref | Package | Side | Pin 1 at (x, y mm) | Pin-1 corner, top view |
  |---|---|---|---|---|
  | U7 flash, U9 HyperRAM | BGA-24 | Top | (95.69, 100.75), (86.55, 100.75) | lower-left |
  | U10 | TSSOP-16 | Top | (80.58, 118.14) | upper-right |
  | U11 | SOT-23-5 | Top | (76.45, 114.21) | upper-left |
  | U12 | UQFN-8 | Top | (78.50, 108.28) | upper-right |
  | D1, D2 | side-view RGB LED | Top | pad 1 on the left; lens must face the north board edge (away from J1) | middle-left |
  | U2, U4, U17 | SOT-563 | Bottom | (105.11, 111.36), (105.22, 116.35), (104.14, 123.68) | upper-right |
  | U3, U18 | SOT-563 | Bottom | (76.31, 102.28), (81.13, 98.73) | lower-left |
  | U6 | SOT-23-5 | Bottom | (85.80, 122.48) | upper-right |
  | U8 | UQFN-16 | Bottom | (101.01, 102.25) | upper-right |
  | U13 | TSSOP-16 | Bottom | (76.03, 118.34) | upper-left |
  | U14 | SOT-23-5 | Bottom | (78.34, 116.01) | lower-right |
  | U15 | UQFN-8 | Bottom | (80.90, 112.67) | upper-left |
  | X1 | 3225 oscillator | Bottom | (93.07, 96.11) | upper-left |

  Compare against the board in KiCad (`hardware/control_card.kicad_pcb`, View → Flip Board for the bottom side). A
  rotated regulator or level shifter can destroy the FPGA, so this check is mandatory.
- [ ] **Solder joints:**
  - no bridges on the TSSOPs (U10, U13), the SOT-563 bucks (U2–U4, U17, U18) or the UQFNs (U8, U12, U15);
  - no tombstoned 0201s under the BGA (bottom side, C21–C46, C66–C76);
  - BGAs sit flat. If JLC supplied X-ray images of U1/U7/U9, look for voids and bridges.
- [ ] **Hand-soldered J1 and J2:** no bridges between the 1.27 mm-pitch J1 pins. J1 pin 1 is the square pad.
- [ ] **Bottom-side parts present** (121 of the 161 assembled parts are on the bottom). Compare with the 3D renders
  `docs/img/board_top.png` and `docs/img/board_bottom.png` (final design; U1, U7 and U9 show as bare pads because their
  footprints have no 3D model, and J1/J2 are drawn although they're soldered by hand).

## 2. Resistance checks (no power)

With a multimeter on resistance (black lead on GND, e.g. J1 pin 2), let each reading settle; the large capacitors
charge from the meter. Measure every rail in the rail table.

- [ ] **No rail below 1 Ω to GND.** A reading under 1 Ω is a short: stop and find it (thermal camera at low current, or
  look for solder bridges).
- [ ] **Compare the boards with each other.** A rail that is clearly lower on one board than on the others points to an
  assembly fault. +0V75 is expected to be the lowest (FPGA core); the others normally read hundreds of Ω or more.
- [ ] **Rail to rail:** +5V to +3V3, +3V3 to +1V8, +1V8 to +0V75, +1V8 to +1V8_HR, +1V8 to +1V2 and +3V3 to +3V3A are
  not shorted to each other.
- [ ] **Configuration straps** (power off, to GND or to +1V8):
  - MSEL2 (R13 4.7 k to GND fitted, R14 pull-up DNP);
  - MSEL1 (R12 4.7 k to +1V8);
  - AS_nCS/MSEL0 (R11 4.7 k to +1V8);
  - RREF_SDM R19 2 k to GND;
  - TCK R20 1 k to GND on the header side.

## 3. First power-up (current-limited, no J1 connection to the power board)

Feed +5V and GND into J1 pin 1 and pin 2 (or 35/36) from a bench supply with a current limit. Don't plug the card into
the power board yet.

- [ ] **Current limit 300 mA**, then ramp the supply to 5.0 V. Record the current.
  - With no configuration in the flash, the FPGA stays unconfigured. Expect roughly 0.1–0.5 A. Agilex 3 static current
    isn't documented here; record it and compare between boards.
  - If the supply goes into current limit, stop and go back to section 2.
- [ ] **Measure every rail** in the rail table. All within ±3 % of nominal.
- [ ] **Enable and power-good chain:** EN_0V75 (R46 pin 2), PG_0V75 (R5 pin 2), PG_1V8 (R8 pin 2) and PG_3V3 (R50
  pin 2) all at ≈3.33 V. A net at ≈5 V has lost its 200k to GND, so that buck runs in PFM.
- [ ] **Sequence, with a scope** (4 channels: +0V75, +1V8, +3V3, then +1V2 and +1V8_HR in a second capture; trigger on +5V or on +0V75 rising):
  - order is +0V75 → +1V8 → +3V3, then +1V2 and +1V8_HR together. Each rail reaches about 90 % before the next one starts;
  - every ramp is monotonic, with no dips or restarts;
  - +1V8 reaches its level within 10 ms (AS normal mode requires VCCIO_SDM within 10 ms; see `docs/agilex3_requirements.md` section 3).
- [ ] **Ripple:** under 1 % peak-to-peak on +0V75 and +1V8 at no load (20 MHz scope bandwidth, short ground spring at the
  output capacitor).
- [ ] **Forced PWM:** at no load, each switch node (L1, L2, L3, L4, L5 pad 1) switches continuously at about 2.2 MHz
  (the core buck near 2.1 MHz, at its minimum on-time), with no bursts or gaps. Bursts mean that buck is in PFM: check
  its EN voltage.
- [ ] **Ripple on +1V2 and +1V8_HR**, the two rails that were LDOs before: record peak-to-peak at no load and after
  configuration. Compare with the VCCRCORE, VCCIO_PIO and VCCIO_HVIO limits in the Agilex 3 data sheet. Optionally
  remove R51 on one board to compare PFM.
- [ ] **Raise the limit to 1 A.** Nothing gets hot: touch test or thermal camera on U2–U4, U17, U18, U6 and U1.

## 4. Clock and static levels

- [ ] **Oscillator:** 100 MHz at X1 pin 3 or at either end of R25. Level 0–1.8 V. Use a ≥500 MHz scope with a short
  ground, or a frequency counter.
- [ ] **nSTATUS and nCONFIG:** nSTATUS (U1.AJ48, pull-up R18) and nCONFIG (U1.BG51, pull-up R17) sit at 1.8 V.
  - With an empty flash the SDM can't load a bitstream. nSTATUS may then go low or pulse; that is acceptable here.
  - Measure on the pull-up resistor pads, not on the balls.
- [ ] **HR_RESET_N** (R24 pin 2) high at 1.8 V.

## 5. JTAG

The header side of U8 is 3.3 V and J2 has no reference-voltage pin, so the adapter must drive 3.3 V levels.

- [ ] **Wire the adapter:** J2 pin 1 TCK, pin 2 TDI, pin 3 TMS, pin 4 TDO, pin 5 GND.
- [ ] **Scan the chain:**
  - Quartus Prime Pro (a version that supports A3CZ065BB18AE7S) with a supported cable (USB-Blaster II, or an
    FTDI-based Altera-compatible cable): run `jtagconfig`. It must list one device, an Agilex 3 A3CZ065.
  - With a plain FTDI module that Quartus doesn't support, first check the chain with OpenOCD's `ftdi` driver: an IDCODE
    scan only. Compare the IDCODE with the A3CZ065 BSDL file from Altera.
- [ ] **If the chain is broken:**
  - check +1V8 (U8 VCCB, pin 13) and +3V3 (VCCA, pin 14);
  - DIR1–DIR3 tie to +3V3 (A→B, for TCK, TDI and TMS), and TDO runs B→A;
  - look for solder faults on U8 (UQFN-16, bottom side).

## 6. First FPGA design (JTAG, SRAM object file)

Create a Quartus Pro project for A3CZ065BB18AE7S. Pin assignments come from `reference/pin_assignment.csv` (columns: net,
ball, bank, dir, use, pin_name):

```
set_location_assignment PIN_<ball> -to <net>
set_instance_assignment -name IO_STANDARD "1.8-V LVCMOS" -to <net>   # banks 6C and 6D
set_instance_assignment -name IO_STANDARD "3.3-V LVCMOS" -to <net>   # all other banks
```

Device and Pin Options:
- configuration scheme Active Serial x4;
- device initialization clock OSC_CLK_1 100 MHz;
- active serial clock 100 MHz.

Check the generated `.qsf` for the exact assignment names your Quartus version writes.

- [ ] **Blink design:** clock from CLK100M (pin D18), a counter, LEDs driven active low.
  - Cycle LED1 R, G, B, then LED2 R, G, B, about 0.5 s each.
  - Confirm each colour lights in the right LED. A wrong colour means a pin swap: compare with `pin_assignment.csv`.
- [ ] **Fitter pin report:** compare the Fitter `.pin` file with `reference/pin_assignment.csv`. Every net must be on the
  listed ball, and banks 6C/6D must be at 1.8 V.
- [ ] **Current:** record the supply current while the design runs.

## 7. Configuration flash (Active Serial x4)

- [ ] **Make the programming file:** in Programming File Generator, create a `.jic` for Active Serial x4 with the
  configuration device MT25QU256 (Micron 256 Mb, 1.8 V). Program it over JTAG with Quartus Programmer.
- [ ] **Boot from flash:** power-cycle the 5 V supply. The blink design must start by itself within about a second.
- [ ] **Repeat ten times:** power-cycle at least 10 times and check that it boots every time. A board that sometimes fails
  points at the power-up order or at the 10 ms rule in section 3.

## 8. HyperRAM (U9, bank 6D)

- [ ] **Controller:** use a HyperBus controller, either Altera's HyperBus/HyperRAM IP if your Quartus version offers it
  for Agilex 3, or an open-source one. HR_CK is single-ended (CK# unused). The data lines are length-matched to 10.8 mm;
  HR_CK is 12.9 mm long and is meant to be phase-adjusted in the controller.
- [ ] **ID registers:** read ID0/ID1. The values must match the W958D8NBYA datasheet.
- [ ] **Memory test** over the full 32 MB (walking ones and zeros, address-in-address, random data):
  - first at a low clock (e.g. 50 MHz);
  - then step up to the target clock. Check the HVIO bank speed limit against the HyperRAM clock; this is an open item.
- [ ] **Bit order:** a failing single DQ bit or nibble points at the DQ wiring. Each net HR_DQn reaches memory pin DQn
  (fixed 2026-10-19). Check with the schematic sheet "HyperRAM and clock".

## 9. ADCs

- [ ] **Read both ADCs** over SPI:
  - start with SCLK at 10 MHz, CS low, 18 clocks per conversion, data on SDO;
  - the target is 60 MHz SCLK for 2.5 MSPS;
  - the series resistors are 33 Ω, so sample SDO with a clock you can phase-adjust.
- [ ] **Select mux channels:** with ADASEL0–2 (U10, ADC A) and ADBSEL0–2 (U13, ADC B).
  - Which J1 pin feeds which mux input is in `reference/mux_assignment.csv` and `reference/power_board_header.csv`.
- [ ] **Known inputs:** apply DC voltages (0.5, 1.65 and 3.0 V) through a resistor to the J1 analog pins.
  - Expect code ≈ V / 3.3 V × 16384. AVDD = +3V3A is the reference, so measure +3V3A and use the measured value.
  - Check every channel of both muxes.
- [ ] **Noise:** with an input grounded through 0 Ω, the code spread should be a few LSB.

## 10. J1 interface to the power board

- [ ] **Map before connecting:** check every J1 signal against `reference/power_board_header.csv`. Pins are mirrored: card
  odd pin n mates with power-board pin n+1.
  - Two power-board labels differ from the card's: `heater_cap_ad_meas` vs `heater_cap_meas`, and `Cuk_cap_meas_raw`.
    Check whether those analog pins are actually connected on the power board.
  - **PRI_DHB_HI / PRI_DHB_LO:** in the power board's KiCad transcription (`/home/jari/dev/tube_psu_kicad`), the Si8274
    (DRV5) PWM input, pin 1, is driven by the card's **PRI_DHB_LO**, and PRI_DHB_HI goes to its pin 2 (NC1). That is
    the opposite of `reference/power_board_header.csv`. Confirm on the original tube_power 5.1 schematic before writing
    the half-bridge PWM firmware.
  - **Pull-downs:** the power board has 10 k pull-downs on PRI_DHB_HI/LO, EPWM5A, EPWM6A and PFC_PWM1/2. The card adds
    R40/R41 (10 k) on EPWM2A/EPWM2B, which drive the power board's Si8661 isolator inputs. EPWM1A goes nowhere on the
    power board.
- [ ] **Outputs:** toggle each FPGA output (EPWM*, PRI_DHB_*, CUK_CS, GPIO_*) from a test design and probe it at its J1
  pin: 0/3.3 V levels and correct pin.
- [ ] **Inputs:** drive each J1 input at 3.3 V with a pull resistor and read it back in the FPGA.
- [ ] **First connection to the power board:** do it with the power stage's high voltage disconnected, and the PWM
  outputs held in their safe state by the design.

## 11. Load and temperature

- [ ] **Full-load design:** run the largest planned design, or a toggling stress design.
  - Measure the +0V75 current: the 5 V input current × 5 V × efficiency / 0.75 V, or measure across L1.
  - Compare with the Power and Thermal Calculator estimate. The core regulator AP61302 is rated 3 A; this is an open item.
- [ ] **Temperatures** after 10 minutes: U1, the bucks U2–U4, U17, U18 and the analog LDO U6 stay within their ratings (thermal camera or
  thermocouple).

## 12. Result log

Fill in one column per board (serial number written on the board with a marker).

| Check | Board 1 | Board 2 | Board 3 | Board 4 | Board 5 |
|---|---|---|---|---|---|
| Visual / orientation OK | | | | | |
| R to GND: +0V75 / +1V8 / +3V3 / +5V (Ω) | | | | | |
| Idle current at 5 V, unconfigured (mA) | | | | | |
| +0V75 / +1V8 / +3V3 / +1V2 / +1V8_HR / +3V3A (V) | | | | | |
| Sequence OK, +1V8 rise time (ms) | | | | | |
| 100 MHz clock OK | | | | | |
| JTAG chain OK | | | | | |
| Blink design OK, current (mA) | | | | | |
| Boots from flash, 10/10 | | | | | |
| HyperRAM test (max clock passed) | | | | | |
| ADC A / B linearity OK | | | | | |
| J1 outputs / inputs OK | | | | | |
| Full-load +0V75 current (A), temperatures (°C) | | | | | |

## If something fails

- **Look up the net:** in the KiCad schematic, then the board.
- **Don't trust older notes:**
  - `docs/order_checklist.md` and `docs/design-notes.md` hold the design history; some notes there predate later changes;
  - the regeneration scripts in `tools/` are not used any more (the design was hand-edited afterwards). Don't run
    `tools/gen_schematic.py` or `tools/build_pcb.sh`.
- **Fixes:**
  - track rework in `hardware/` and note it in the result log;
  - collect design fixes for the next revision in a new section at the end of this file.
