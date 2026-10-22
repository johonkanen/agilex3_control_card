# Production checklist: KiCad project and JLCPCB files

For whoever verifies the design and order files before they go to JLCPCB, human or agent, starting with no prior context.
Each item has a command or a place to look, and the expected result. Stop and report at the first item that doesn't
match. Section 9 lists deviations already reviewed and accepted, so don't re-raise those.

## 0. Context and tools

- **The design:** a 6-layer FPGA control card (Altera Agilex 3 A3CZ065BB18AE7S), KiCad 10.
  - Project: `hardware/control_card.kicad_pro`.
  - Design rules: `hardware/control_card.kicad_dru`, which adds JLC-specific rules on top of the project's minimums.
  - Read `README.md` first.
- **The order:** PCB and assembly at JLCPCB, both sides.
  - U1 (the FPGA) through JLC Global Sourcing.
  - J1 and J2 are not assembled.
- **KiCad CLI:** KiCad 10 AppImage, unpacked: `./kicad-10.0.7-x86_64.AppImage --appimage-extract`. Then
  `K=<path>/squashfs-root` and:
  - CLI: `$K/AppRun kicad-cli`;
  - KiCad's Python: `$K/AppRun python3.11 -I`.
  - DRC on a copy of the board only applies the project rules if `control_card.kicad_pro` and `control_card.kicad_dru` sit
    next to it. Copy the whole `hardware/` folder.
- **JLC part search:** `python3 -I tools/jlc_search.py <C-number or keyword> -n 5`. In Python, `tools/jlc_search.search(kw, n)`
  returns the raw records.
- **Don't run** `tools/gen_schematic.py` or `tools/build_pcb.sh`. They regenerate the design from scratch and would
  overwrite the hand edits and routing.

## 1. Design checks in KiCad

- [ ] **ERC:** `$K/AppRun kicad-cli sch erc -o /tmp/erc.rpt hardware/control_card.kicad_sch`.
  - Expected: exactly 1 violation, `ground_pin_not_ground` for U1 GNDSENSE. This is intended: it is the core regulator's
    remote-sense return.
- [ ] **DRC:** `$K/AppRun kicad-cli pcb drc --refill-zones --schematic-parity -o /tmp/drc.rpt hardware/control_card.kicad_pcb`.
  - Expected: **0 unconnected items, 0 schematic parity issues**. The only violations should be silkscreen ones
    (`silk_edge_clearance`, `silk_over_copper`, `silk_overlap`; about 30 at the last check).
  - Any `clearance`, `hole_clearance`, `track_width`, `annular_width`, `length_out_of_range`, `shorting_items` or
    `track_dangling` entry is a failure.
- [ ] **The JLC-specific rules are present** in `hardware/control_card.kicad_dru`:
  - `jlc_pth_hole_to_copper`: PTH hole to other-net tracks 0.28 mm;
  - `jlc_pth_to_via`: 0.2 mm;
  - `jlc_pth_hole_to_hole`: 0.45 mm;
  - `hyperram_length`: HR_* except HR_CK, 10.7–10.9 mm.
- [ ] **Project minimums** in `hardware/control_card.kicad_pro`, under `board.design_settings.rules`:

  | Setting | Value |
  |---|---|
  | min clearance | 0.1 mm |
  | min track width | 0.09 mm |
  | min via diameter | 0.25 mm |
  | min through-hole | 0.15 mm |
  | min via annular ring | 0.05 mm |
  | min hole clearance | 0.2 mm |
  | min hole-to-hole | 0.2 mm |
  | copper to edge | 0.3 mm |

## 2. Compare with JLCPCB's current capabilities

Open https://jlcpcb.com/capabilities/pcb-capabilities. Capabilities change, so compare against the page, not memory.
The numbers below are what the board uses, measured with KiCad's Python on the last revision.

| Feature | This board | Check against JLC (6-layer, 1 oz outer / 0.5 oz inner) |
|---|---|---|
| Layers / thickness | 6 / 1.6 mm | 6-layer, 1.6 mm offered |
| Size | 32.5 × 33.8 mm (outline) | above the minimum board size for assembly |
| Min track width / spacing | 0.09 mm rule, 0.1 mm the narrowest used (853 segments) / 0.1 mm | multilayer min trace/space |
| Vias (diameter / drill), count | 0.25/0.15 × 217 (216 of them in BGA or 0201 pads), 0.3/0.15 × 73, 0.35/0.2 × 37, 0.45/0.25 × 27 | min via 0.15 mm drill / 0.25 mm diameter for multilayer |
| Via-in-pad | 267 vias sit in SMD pads | needs **epoxy-filled and capped vias (POFV)**: free on 6+ layers |
| Plated holes | 0.559 mm × 50 (J1, 0.813 mm pads), 1.0 mm × 5 (J2, 1.7 mm pads) | min PTH and annular ring |
| Drill tool sizes | 0.15, 0.20, 0.25, 0.559, 1.0 mm; no NPTH | |
| Copper to board edge | ≥ 0.3 mm rule | routed-edge clearance |
| BGA | 0.65 mm minimum ball spacing (U1), 0.30 mm pads; 1.0 mm (U7, U9) | min BGA pad and pitch |
| Smallest SMD pads | 0.2 mm (UQFN-8/16 leads), 0201 passives on the bottom | assembly: 0201 and both sides supported |
| Silkscreen | text hidden; outlines 0.15 mm | min silkscreen line width |

- [ ] **Every line within JLC's limits.** If JLC's limit is tighter than the board's value, report it with the affected
  item count, and don't change the design.
- [ ] **Stackup:** compare the board stackup (KiCad Board Setup → Physical Stackup, or the `(stackup` block in the
  `.kicad_pcb`) with JLC's 6-layer 1.6 mm stackup list.
  - Board: outer prepreg 0.1 mm "2313", core 0.565 mm, inner prepreg 0.127 mm "2116".
  - No impedance control is needed. Any JLC 6-layer 1.6 mm stackup is acceptable; note which one the quote uses.

## 3. Generate the order files

- [ ] **Regenerate** from the current commit:
  `KICAD_ROOT=$K tools/fab_outputs.sh`. Files older than the last board commit are stale.
- [ ] **Expected console summary:**
  - `Found 0 unconnected items`, `Found 0 schematic parity issues`;
  - `BOM: 43 lines, 141 parts; CPL: 141 placements; left out: J1, J2` (the counts change if parts were added);
  - a `rotation:` line listing the package offsets;
  - `no LCSC number (Global Sourcing / consigned): U1 (A3CZ065BB18AE7S)`.
- [ ] **Output in `hardware/fab/`:**
  - `control_card_gerbers.zip`;
  - `bom_jlcpcb.csv`;
  - `cpl_jlcpcb.csv`;
  - `drc.rpt`.

## 4. Gerber and drill files

- [ ] **Zip contents** (`unzip -l hardware/fab/control_card_gerbers.zip`), 16 files:
  - copper F_Cu (`.gtl`), L2_GND (`.g1`), L3_SIG_1V8_1V2 (`.g2`), L4_0V75_3V3 (`.g3`), L5_GND (`.g4`), B_Cu (`.gbl`);
  - F/B mask, paste and silkscreen;
  - Edge_Cuts (`.gm1`);
  - PTH.drl and NPTH.drl (empty, no NPTH holes);
  - the `.gbrjob` job file.
- [ ] **Layer order:** open the zip in a Gerber viewer (KiCad GerbView, or JLC's online viewer after upload). Inner
  layer order is L2 GND, L3 1.8/1.2 V planes, L4 0.75/3.3 V planes, L5 GND. JLC must read the 6 copper layers in that
  order. Check the order JLC's viewer shows.
- [ ] **Outline:** one closed board outline, about 32.5 × 33.8 mm.
- [ ] **Drills:** the drill hits line up with the pads in the viewer, with J1's 50 holes along the south edge and J2's 5
  holes on the east side. Tool list:
  `unzip -p hardware/fab/control_card_gerbers.zip control_card-PTH.drl | grep -E '^T[0-9]+C'` gives
  0.15/0.2/0.25/0.559/1.0 mm.
- [ ] **Silkscreen:** the F/B silkscreen files contain outlines and pin-1 marks only, no reference text (hidden on
  purpose).
- [ ] **Paste:** the bottom paste layer has openings for the 0201s, and the top paste layer for the U1 BGA. BGA paste is
  0.30 mm for 0.30 mm pads.

## 5. BOM and LCSC parts

- [ ] **Format:** `bom_jlcpcb.csv` has the header `Comment,Designator,Footprint,LCSC Part #`. Every row except U1 has a
  C-number.
- [ ] **Designators match:** the BOM designators equal the CPL designators exactly (141 each). J1 and J2 are absent from
  both.
- [ ] **Footprint matches JLC's package.** For each LCSC number, `tools/jlc_search.py <C-number>`, then compare the package
  with the footprint size:
  - an `R_0201`/`C_0201` footprint needs a 0201 part, `_0402` a 0402 part, and so on;
  - SOT-23-5 and SOT-563 must match exactly;
  - the BGA-24 parts (U7 flash, U9 HyperRAM) are 6×8 mm.

  A mismatch is a failure. R27–R33 were once 0402 parts on 0201 pads, and that was fixed.
- [ ] **Stock that can actually be ordered.** Use the `canPresaleNumber` and `minPurchaseNum` fields from
  `jlc_search.search()`, not `stockCount`.
  - Required for each part: `canPresaleNumber ≥ quantity per board × number of boards`, and `minPurchaseNum == 1`.
  - `stockCount` can hide oversold parts. The 49.9 k resistor C25897 showed 831 in stock while −38942 were orderable,
    and was replaced with C137969.
  - Lowest margins at the last check: ADS7056IRUGR C2669798 (2 per board, 34 orderable), MT25QU256 C2061023 (445),
    AP61302 C3193204 (678).
- [ ] **Extended parts:** count the extended parts (`componentLibraryType == "expand"`), about 25. Each adds JLC's one-off
  extended-part fee; report the total.
- [ ] **U1:**
  - DigiKey/Mouser part A3CZ065BB18AE7S, matched through Global Sourcing in the order's BOM step, or consigned;
  - confirm the exact part number (Z spec, B18A package, E7S grade).
  - Global Sourcing adds lead time; note the quoted date.
- [ ] **DNP:** the BOM excludes DNP parts. R14 (MSEL2 pull-up) is DNP and must not be in the BOM.

## 6. CPL (placement) and rotations

- [ ] **Format:** `cpl_jlcpcb.csv` has the header `Designator,Mid X,Mid Y,Layer,Rotation`, 141 rows. Layer is `Top` or
  `Bottom`: 36 top and 105 bottom at the last check.
- [ ] **Coordinates:** taken from the board origin used by the Gerbers. After upload, every part must land on its pads in
  JLC's preview. A uniform offset means an origin problem.
- [ ] **Rotation convention** (`tools/jlc_bom_cpl.py`):
  - bottom parts are 180° − KiCad angle;
  - package offsets come from the kicad-jlcpcb-tools table (SOT-23 +180°, TSSOP/SOIC/QFN +270°, and so on);
  - a per-part override is possible with a footprint field `JLC Rotation Offset`.
- [ ] **JLC placement preview:** check every polarized part. Pin 1 must be at the corner listed in
  `docs/bringup_checklist.md`, section 1. These packages have no table entry and are most likely wrong:
  - UQFN U8, U12, U15;
  - SOT-563 U2, U3, U4;
  - BGAs U1, U7, U9;
  - oscillator X1;
  - side-view LEDs D1, D2: the lens must point at the north board edge, away from J1.

  Fix any wrong part in the preview, or add `JLC Rotation Offset` in KiCad and regenerate. Then record which.
- [ ] **Two-terminal parts:** a 0° or 180° flip makes no difference. A 90° error is visible as a part across its pads; fix
  it in the preview.

## 7. Order form settings

PCB:
- [ ] 6 layers, 1.6 mm, FR-4 TG155 or better (the default for 6 layers).
- [ ] **Via covering: "Epoxy Filled & Capped"** (POFV). Required: 267 vias are in pads.
- [ ] **Surface finish: ENIG.** Needed for flat pads under the 0.65 mm BGA and the 0201s.
- [ ] Copper: outer 1 oz, inner 0.5 oz.
- [ ] Min via hole 0.15 mm and min via diameter 0.25 mm, as the quote's via options state.
- [ ] Impedance control: none.
- [ ] Mark on PCB (order number): "Remove" or "Specify location". The board has no free silkscreen area reserved for it.
- [ ] Panel: single boards. Edge rails and fiducials "Added by JLCPCB" if assembly asks for them; the board has no
  fiducials of its own.

Assembly:
- [ ] Both sides (36 parts on top, 105 on the bottom).
- [ ] Upload `bom_jlcpcb.csv` and `cpl_jlcpcb.csv`. All 42 lines with a C-number match automatically; U1 via Global
  Sourcing.
- [ ] Quantity: the number of boards to assemble. Check against the lowest stock (the ADS7056, 2 per board).
- [ ] Optional: X-ray inspection for the BGAs (U1, U7, U9).

## 8. After the quote

- [ ] **Preview:** JLC's rendered board matches `docs/img/board_top.png` and `board_bottom.png` in outline and part
  positions. The renders predate the final routing, so only compare the parts.
- [ ] **DFM:** read JLC's DFM/engineering questions. A query on via-in-pad, BGA pads or 0201s is expected; answer with
  the values above.
- [ ] **Record:** the order number, the stackup code, the parts that were rotated in the preview, and the U1 source. Write
  them at the end of this file.

## 9. Deviations already reviewed and accepted

- **ERC GNDSENSE warning:** intended, the core remote-sense return.
- **About 30 silkscreen DRC warnings:** outlines near the board edge (mostly along J1), and small outline overlaps. JLC
  clips silkscreen at the edge.
- **Hidden reference designators:** no room to make them readable. Silkscreen outlines are 0.15 mm, while JLC states
  about 0.153 mm as the minimum line; they may print thin.
- **R31 uses a `C_0201` footprint** with a 0201 resistor (RC-01W33R0FT, C320843). The pads are the same size as the
  resistor footprint's, so it's only a naming oddity.
- **Vias in passive pads:** 0.35/0.2 and 0.45/0.25 vias sit in some 0402/0603 pads (power and GND). They are filled and
  capped by POFV.
- **One 0.25/0.15 via outside a pad.** JLC's 6-layer minimum via allows it.
- **U1 has no LCSC number:** Global Sourcing or consigned.
- **J1/J2 not in the BOM/CPL:** soldered by hand.
- **`reference/bom_draft.csv`** is out of date (the generator's input). The BOM that counts is `hardware/fab/bom_jlcpcb.csv`.
