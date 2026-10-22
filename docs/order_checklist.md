# Hand-off checklist: from here to a JLCPCB order

Board state after the clock move to D18 (2026-10-18):
- no copper DRC errors with the JLC rules in `hardware/control_card.kicad_dru`;
- schematic and board match;
- 23 unrouted signal items, listed in section C.

Work through A → F. Tick each box.

## A. Placement review findings (fix BEFORE hand routing: a rebuild overwrites routing)

From the scripted review and 3D renders (2026-10-17):

- [x] **ADC front ends: fixed in the placement pass (a10f926).** Kickback RC and AVDD caps now sit at the pins, on the
      ADC's own side (ADS7056 datasheet section 11.1):

      | | Before | After |
      |---|---|---|
      | U15 (ADC B): R30 / C61 / C63 / C62 | 11.9 / 3.1 / 8.4 mm / opposite side | 1.8 / 1.4 / 1.5 / 2.2 mm, same side |
      | U12 (ADC A): R26 / C56 / C58 / C57 | 4.2 / 1.5 / 4.1 / 3.7 mm | 2.2 / 1.5 / 1.5 / 3.0 mm |

      The same pass fixed the buck GND pours: they now span the parts' courtyards. Before, the 1.8 V buck's pour reached
      over the ADC B area because its extent included part text.
- [ ] **1.8 V buck (U3, your hand placement): input cap is 3.4 mm from VIN.** The other two bucks have 1.4–1.5 mm. Move it
      closer if there is room; it shortens the switching input loop.
- [ ] **Five ball-pair 1 µF caps ended up just outside the BGA** (C26–C28 on +0V75, C35–C36 on +1V8, 5–7 mm from their
      balls), because the filters took those ball pairs. They still work as near bulk. Accept, or drop them to 0402 at the
      BGA edge.
- [ ] **Silkscreen:** 199 overlapping or mask-clipped reference designators, unreadable in the dense areas. Cosmetic.
      Optionally hide the bottom-side references or move the worst ones.
- [ ] **No 3D models for U1, U7, U9, D1, D2** (custom footprints), so the 3D view can't check their bodies. Look at J1's
      mating side and the LED lenses at the north edge in KiCad's 3D viewer.
- [ ] Checked OK:
  - no pads of different parts closer than 0.15 mm;
  - nothing within 0.5 mm of the edge except D1 (deliberate, 0.3 mm, as on U25) and C12/R5 (0.5 mm);
  - buck loops U2/U4: input cap 1.4/1.5 mm, inductor 1.9 mm;
  - two-sided assembly: 40 parts on top, 103 on the bottom.

## B. Circuit review (manual)

Power (`docs/agilex3_requirements.md` has the FPGA rules):
- [ ] Buck outputs:
  - core: 0.6 × (1 + 49.9k/200k) = 0.750 V (A3CZ065 is −7S, so 0.75 V is right);
  - 1.8 V: 200k/100k;
  - 3.3 V: 200k/44.2k = 3.31 V.
- [ ] Core current: run the Power and Thermal Calculator on the 065 design. AP61302 is rated 3 A.
- [ ] Power-up chain: 0.75 V PG → 1.8 V EN → 1.8 V PG → 3.3 V EN; the 1.2 V and banks-6C/6D 1.8 V LDOs follow +3V3 (group 2B).
- [ ] Bead filters (BLM18PG121SN1D + 47 µF + 1 µF) on VCCPLLDIG_SDM, VCCPLL_SDM, VCCADC, VCCRCORE, plus the oscillator.
- [ ] Analog 3.3 V: TLV75533 from +5V, feeding the muxes, buffers and ADC AVDD.

FPGA and configuration:
- [ ] MSEL = 011 (AS normal): MSEL0 and MSEL1 4.7 k up, MSEL2 4.7 k down (the pull-up is DNP).
- [ ] nCONFIG and nSTATUS: 10 k to 1.8 V. RREF_SDM: 2 k 1 %.
- [ ] Flash MT25QU256ABA8E12 (1.8 V): RESET# (A4) to AS_nRST only; DQ2/DQ3 10 k pull-ups.
- [ ] JTAG through SN74AVC4T774: TCK/TDI/TMS A→B (3.3 → 1.8 V), TDO B→A; DIR and OE ties; header pinout matches your
      FTDI flying leads.
- [ ] Clock: 100 MHz OT3225100MJBA4SL, R25 33 Ω at the source, short branches to D18 (PLLREFCLK1, bank 6D at 1.8 V) and BB44 (OSC_CLK_1).

Memory and I/O:
- [ ] HyperRAM W958D8NBYA5I on +1V8_HR / bank 6D; HR_RESET_N 10 k pull-up; CK# unused (single-ended clock).
- [ ] ADC chains: mux → OPA365 → 33 Ω/680 pF C0G → ADS7056; AVDD 4.7 µF + 100 nF; CS/SCLK/SDO 33 Ω.
- [ ] **J1 pinout vs the power board** (mirrored mapping, `reference/power_board_header.csv`): pin 1 = 5 V, GND pins, every
      signal's direction.
- [ ] Power-board labels that don't match on the tube_power 5.1 schematic: `heater_cap_ad_meas` vs `heater_cap_meas`, and
      `Cuk_cap_meas_raw`. Those J1 analog pins may be unconnected on the power board.
- [ ] LEDs: common anode to 3.3 V, cathodes through 100 Ω, so active low.
- [ ] FPGA build: Quartus test build with `reference/pin_assignment.csv`
      - banks 6C and 6D 1.8-V LVCMOS, other banks 3.3-V LVCMOS;
      - Active Serial x4, `OSC_CLK_1_100MHZ`, `AS_FREQ_100MHZ`;
      - then compare the Fitter's `.pin` file with the netlist (Claude can script this).

## C. Hand routing

- [ ] Close and reopen the board in KiCad (it was regenerated).
- [ ] Route the 23 unrouted items (17 nets; a count in brackets means that many breaks in the net):
  - ADC digital, short runs between each ADC, its series resistors and the FPGA: ADCA_SDO_R, ADCB_SCLK_R, ADCB_SDO,
    ADCB_SDO_R, ADASEL0;
  - analog: MUXA_OUT (ADC A mux to OPA365 input) and ADB6 (J1 to mux B). Keep them short and away from digital lines;
  - configuration/JTAG (SDM corner, 1.8 V): AS_DATA2 (2), AS_DATA3 (2), AS_NCS_MSEL0 (2), TDI (2), TDO_1V8 (2),
    TMS_1V8;
  - others: HR_RESET_N (2), J1_P26, LED2_R, SYNCH_2.
  - CLK100M (R25 → D18 and → BB44) is already routed by the scripts.
- [ ] Rules while routing (already in the DRC):
  - tracks ≥ 0.09 mm (presets 0.1/0.15/0.2/0.3/0.5);
  - vias 0.3/0.15 (0.25/0.15 only as via-in-pad);
  - tracks ≥ 0.28 mm from J1/J2 pin holes; a 0.1 mm track centred between J1 pins fits.
- [ ] DRC (Inspect → Design Rules Checker, refill zones): 0 errors and 0 unconnected. Silkscreen warnings are OK.

## D. Fabrication files

- [ ] `KICAD_ROOT=<unpacked KiCad AppImage> tools/fab_outputs.sh` writes `hardware/fab/`:
  - Gerbers and drill zip;
  - `bom_jlcpcb.csv` and `cpl_jlcpcb.csv`;
  - `drc.rpt`.

  Check the printed summary: J1/J2 are left out, U1 has no LCSC number.
- [ ] Open the zip in JLC's (or KiCad's) Gerber viewer and check:
  - 6 copper layers in order: L2/L5 GND, L3 1.8/1.2 V, L4 0.75/3.3 V;
  - board outline;
  - drill hits.

## E. JLCPCB order

PCB:
- [ ] 6 layers, 1.6 mm. Stackup: JLC's "2313" build, as set in the board. Confirm the stackup code in the quote.
- [ ] Outer copper 1 oz, inner 0.5 oz.
- [ ] Min hole 0.15 mm, min via 0.25 mm (BGA via-in-pad).
- [ ] **Via-in-pad: epoxy filled and capped** (POFV). Free on 6 layers, and required for the BGA, flash and HyperRAM.
- [ ] **ENIG** surface finish (flat pads for the 0.3 mm BGA pads, 0201s and the UQFN).
- [ ] Order number: "specify location" or remove; no impedance control needed.

Assembly:
- [ ] Both sides; upload the BOM and CPL.
- [ ] **U1 A3CZ065BB18AE7S: Global Sourcing** (DigiKey $78.40, 84 in stock on 2026-10-16) or consigned parts.
- [ ] J1 (2×25 1.27 mm right angle) and J2 (1×5 2.54 mm) are not in the BOM: buy them and solder them yourself.
- [ ] Check JLC's placement preview, part by part, for rotation and side: SOT-23-5, SOT-563, UQFN-16 (U8), QFN (ADCs),
      TSSOP-16, the BGAs (U1/U7/U9 pin 1), the side-view LEDs (lens toward the north edge), the 0805/0603 polarity-free
      parts.
- [ ] Low stock (2026-10-16): ADS7056 52, MT25QU256 46. Buy or reserve if needed.
- [ ] Extended parts: 23 types; each extended part type adds a one-off setup fee.
- [ ] Panel/edge rails with fiducials. The board has no fiducials of its own, so let JLC add rails, or accept their default.

## F. When boards arrive

- [ ] Before powering: measure resistance to GND on every rail (+5V, +0V75, +1V8, +1V8_HR, +3V3, +1V2, +3V3A).
- [ ] Bench supply with a current limit on J1 pin 1. Check the rails and their order with a scope: 0.75 → 1.8 → 3.3/1.2
      and +1V8_HR.
- [ ] JTAG chain scan (Quartus Programmer, FTDI mini-module), then a test design over JTAG, then the flash.
