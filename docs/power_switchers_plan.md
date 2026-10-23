# Plan: FPGA supplies from switching regulators only

Status (2026-10-23): going into the order revision (the board order hasn't been placed). Schematic done: U17 (+1V2)
and U18 (+1V8_HR) bucks replace U5/U16 (C10/C74 removed; C11/C75 kept as extra output caps), and R46–R51 put all
five bucks in forced PWM. Next: board placement and routing.

Goal: every FPGA rail comes from a buck regulator, and the power section becomes a block that can be reused on
other Agilex boards.

## 1. What changes

| Rail | Now | After | FPGA loads |
|---|---|---|---|
| +0V75 | AP61302 buck U2 (group 1) | unchanged | VCC, VCCL_SDM and the other SDM core rails; +0V75_PLLDIG through FB1 |
| +1V8 | AP61102 buck U3 (2A) | unchanged | VCCPT, VCCPT_HVIO, VCCIO_SDM, VCCFUSEWR_SDM, the flash; +1V8_PLL and +1V8_ADC through FB2/FB3 |
| +3V3 | AP61102 buck U4 (2B) | unchanged; no longer feeds the LDOs | HVIO banks at 3.3 V |
| +1V2 | TLV75512 LDO U5, from +3V3 | **AP61102 buck from +5V** | VCCRCORE (through FB4), VCCIO_PIO_SDM, VCCIO_PIO_3A_T |
| +1V8_HR | TLV75518 LDO U16, from +3V3 | **AP61102 buck from +5V** | VCCIO_HVIO_6C/6D, HyperRAM, the oscillator through FB5 |
| +3V3A | TLV75533 LDO U6, from +5V | **unchanged (stays an LDO)** | none: muxes, buffers and ADCs only |

+3V3A is not an FPGA supply. The ADS7056 and OPA365 gain from an LDO's low noise, so it stays an LDO.

Parts removed: U5, U16 and their capacitors. Parts added: two buck cells, each with:
- an AP61102Z6-7 (C5224055);
- a WPN201610H1R0MT 1 µH inductor (C97002);
- input and output capacitors;
- an FB divider and its feed-forward capacitor (C4/C7 33 pF, as on the existing AP61102 cells);
- an EN pull-up or link.

The cells are copies of the 1.8 V cell U3 with the FB divider changed. About +12 parts per board.

JLC stock on 2026-10-23 (orderable, minimum purchase 1):
- AP61102Z6-7: 947. It goes from 2 to 4 per board, so 40 for 10 boards.
- WPN201610H1R0MT: 1842. It goes from 3 to 5 per board.

## 2. Power-up order

Altera's order (`docs/agilex3_requirements.md` section 3) is group 1 → 2A → 2B, each group at 90 % before the next
starts. Rails may ramp in any order within a group.

The new order:
1. U2 +0V75 (group 1) starts from +5V.
2. PG_0V75 enables U3 +1V8 (2A).
3. PG_1V8 enables U4 +3V3 (2B).
4. **U4's PG, currently unconnected, enables both new bucks** (+1V2 and +1V8_HR, 2B).

This keeps today's behaviour (the 2B LDOs start once +3V3 is up). It also staggers the soft-starts, so less inrush
current flows through the header. PG is open-drain, with only an internal 5 MΩ pull-up to VIN, so the new PG_3V3 net
gets the same divider as the other enable nets (section 2a).

Alternative: tie all three 2B enables to PG_1V8. That is one divider fewer and still within the rules, but three
soft-starts happen at once.

## 2a. Forced PWM on every buck (also applies to the order revision)

Source: AP61100/AP61102 data sheet DS42004 Rev. 6-2, section 3 "Enable"; AP61300/AP61302 data sheet, same section.

The EN pin also selects the mode:
- **PFM at light load:** EN is driven high to more than VIN − 200 mV, for example tied to VIN;
- **PWM regardless of load:** EN is driven high but stays below VIN − 200 mV. The data sheet uses a divider from VIN:
  100 k to VIN and 200 k to GND, which puts EN at 3.33 V from 5 V.

The EN threshold is 0.91 V rising and 0.83 V falling. The cost of PWM is quiescent current: 620 µA instead of 15 µA,
which doesn't matter here.

**On the current board (11b8314), all three bucks run in PFM at light load:**

| Buck | EN net | Driven by | Mode |
|---|---|---|---|
| U2 +0V75 | +5V | tied to VIN | PFM |
| U3 +1V8 | PG_0V75 | R5 100k to +5V (and U2's internal 5 MΩ) | PFM |
| U4 +3V3 | PG_1V8 | R8 100k to +5V | PFM |

Below the light-load boundary (data sheet Eq. 2: I = (VIN − VOUT)/(2L) · tON, with L = 1 µH), the switching
frequency drops with load and the ripple grows:

| Rail | tON at 2.2 MHz | PFM below about |
|---|---|---|
| +0V75 | 68 ns (at the 70 ns minimum, so fSW settles near 2.1 MHz) | 0.15 A |
| +1V8 | 164 ns | 0.26 A |
| +3V3 | 300 ns | 0.26 A |
| +1V2 (new) | 109 ns | 0.21 A |
| +1V8_HR (new) | 164 ns | 0.26 A |

Most of these rails draw less than that on this card. VCCPT asks for a low-noise switching regulator, and
VCCPLL/VCCADC are filtered from it, so a fixed frequency well above the beads' corner is what we want.

The fix adds one resistor per EN net and needs no other change:
- **U2 EN:** cut pin 5 from +5V. Fit 100 k from +5V to EN and 200 k from EN to GND.
- **PG_0V75 and PG_1V8:** add 200 k to GND next to R5 and R8. When PG releases, EN = 5 V · 200/300 = 3.33 V (the
  internal 5 MΩ adds about 0.02 V). When PG is low, EN stays low as before.
- **PG_3V3 (new):** 100 k to +5V and 200 k to GND. It drives both new bucks.

That is 4 resistors on the current design (0201 or 0402, JLC basic parts). Fitting the 200 k parts as normal BOM parts
keeps an easy fallback: removing one returns that buck to PFM, so both modes can be compared at bring-up.

This is a small change to a routed board (one pad off +5V, four resistors), so it could go into the order revision
on its own, before the LDO-to-buck change.

Check in the datasheet:
- the POR delay: with one more PG step, all rails must still be up before the POR timeout;
- in AS normal mode, VCCIO_SDM must be up within 10 ms. That doesn't change, because +1V8 is still second.

## 3. Things to check before the schematic change

1. **Minimum on-time (checked).** 5 V → 1.2 V needs a 109 ns on-time at 2.2 MHz, against a 70 ns typical minimum, so
   that is fine. Data sheet Table 1 for 1.2 V: R1 = R2 = 200 k, 1 µH, 10 µF in and out, C3 = 33 pF on the AP61102.
   1 µH gives about 0.4 A peak-to-peak ripple current.
2. **Light-load mode (resolved).** Forced PWM through the EN divider, section 2a. Still check the ripple limits for
   VCCRCORE, VCCIO_PIO and VCCIO_HVIO (Agilex 3 data sheet, recommended operating conditions) against the measured
   ripple at bring-up.
3. **Filtering.** Keep FB4 (VCCRCORE) and FB5 (oscillator). A buck has more ripple than an LDO, so:
   - check the bead and capacitor values against the noise limit;
   - add a 10 µF after FB5 if the oscillator data sheet asks for supply ripple below a few mV.
4. **FB dividers.** Use the AP61102's 0.6 V reference:
   - 1.2 V: the top resistor equals the bottom one (data sheet: 200k/200k);
   - 1.8 V: 2:1, the same as U3.

   Pick E96 values from JLC basic parts, and check the tolerance stack against each rail's range.
5. **Power-down.** Check whether the Agilex 3 data sheet asks for a power-down order. Today all rails drop together
   when +5V goes away. Bucks with large output capacitors may decay at different rates than the LDOs did.

## 4. Board impact

- **Area.** A buck cell takes about 5 × 6 mm, against about 3 × 4 mm for an LDO and its caps. The board has 109 parts
  on the bottom and is fully routed, so the two cells need space found and rerouting.
  - U5 sits in the right column at (105.3, 123.3), near the core buck. A 1.2 V cell there takes +5V from the
    existing L3 branch up the right side.
  - U16 sits upper-left at (81.8, 97.0), next to the 1.8 V cell. A 1.8 V_HR cell there takes +5V from the west run.
- **Switch nodes.** Five switch nodes then sit near the BGA and the analog chain on the left edge. Keep each SW
  pour small and on the outer layer, over the solid GND planes on L2/L5. Keep the new upper-left SW node away from
  the HyperRAM traces on L1 and the ADC chain.
- **+5V current.** It goes down. An LDO draws its full load current from +3V3, but a buck draws only about Vout/Vin of
  it from +5V. U4 also carries less load.
- Rerun DRC, length matching (`hyperram_length`), the stock check and the fab outputs. Then update
  `pin_assignment.csv` only if the change moves FPGA pins (it shouldn't).

## 5. Making it reusable for other Agilex boards

- **One power sheet** with a cell per rail, each with the same layout as the others. Each cell carries its rail name,
  power group and FB values in the sheet. Copy the cell for a new rail rather than redrawing it.
  - KiCad 10's design blocks or the multichannel layout tool can repeat a routed cell on the board.
- **Pin-compatible current steps.** The AP61102 (1 A) and AP61302 (3 A) share the SOT-563 pinout. Lay out every cell
  with pads for a 2520 inductor (with 2016 parts fitted where 1 A is enough), so a bigger device needs only a BOM
  change.
- **Split VCCIO_PIO from VCCRCORE in the block.** Here they share +1V2, because the HSIO bank 3A is unused. A board
  that uses HSIO for memory needs VCCIO_PIO at the memory's voltage (1.1 V or 1.2 V depending on the standard;
  check the Agilex 3 EMIF guide). That calls for its own buck sized for the memory current, while VCCRCORE stays at
  1.2 V.
- **Current budget per rail.** For each board, take the numbers from Altera's Power and Thermal Calculator. Record
  them next to the cell, together with the regulator and inductor margin. That also closes this board's open item:
  the core current and the L1 rating.
- **Sequencing as a chain of PGs**, documented in the sheet: G1 → 2A → 2B, with any extra 2B rail hanging off the last
  PG.

## 6. Order of work

1. Decide whether this goes into the revision waiting for the FPGAs or into the next one. Do it on a branch, so
   11b8314 stays orderable. The forced-PWM resistors (section 2a) can go into the order revision on their own.
2. Datasheet checks from section 3.
3. Schematic: remove U5/U16 and add the two cells (the user places them; symbols cloned as before).
4. Board: place, route, DRC, length check.
5. Stock check, fab outputs, update the docs (requirements section 3, design notes, bring-up checklist rail table).
