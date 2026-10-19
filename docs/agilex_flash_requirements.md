# Agilex 3 configuration flash: requirements and example parts

What a QSPI flash must do to configure an Agilex 3 in Active Serial x4 (AS x4) mode, and parts that meet it.
The source is the *Device Configuration User Guide: Agilex 3 FPGAs and SoCs* (847422, rev. 2026.04.27), unless
noted otherwise. Stock figures are from JLCPCB on 2026-10-15.

## Requirements

### Must have

1. **1.8 V operation.** The AS pins are powered by VCCIO_SDM (1.8 V LVCMOS). The guide says Agilex 3 supports
   third-party flash "operating at 1.8 V". Use the 1.7–2.0 V families (Micron MT25QU, Winbond W25Q..JW/NW,
   ISSI IS25WP, Macronix MX25U/MX66U, GigaDevice GD25LB/LQ), not their 3 V twins (MT25QL, W25Q..JV, IS25LP, ...).
2. **SFDP (JESD216).** The SDM's generic QSPI controller reads the flash's parameters from its SFDP table
   (guide 3.2.7.1).
3. **A dedicated hardware reset pin** (guide 3.2.7.1). A RESET# shared with DQ3 is not enough, because DQ3 is
   data in x4 mode.
4. **RESET# wired to AS_nRST (SDM_IO15), and to nothing else.** "You must connect the serial flash or quad SPI
   flash reset pin to the AS_nRST pin. The SDM must fully control the QSPI reset. Do not connect the quad SPI
   reset pin to any external host." Wire AS_nRST even if it looks unused (guide Table 35, note 14).
5. **Power-up order:** the flash must be fully powered at the same time as VCCIO_SDM ramps, or before it.

### Good to know

- **Addressing:** the SDM boots from the flash with 3-byte addresses. For 256 Mb and larger it then switches the
  flash to 4-byte addressing (guide 3.2.7.1). Both kinds of part work.
- **Clock:** AS_CLK runs at up to 166 MHz with a 25, 100 or 125 MHz clock on OSC_CLK_1, otherwise slower from
  the internal oscillator. In Quartus, set the maximum to what the flash supports.
- **Size:** the guide's example A3C 025 bitstream (RBF) is about 1 MB (8 Mb), so 128 Mb holds several images,
  for example remote system update with a factory image plus updates. 256 Mb and up leaves room for HPS
  software or user data.
- **Erase sizes:** supported flash offers 4, 32 and 64 KB erase. HPS remote system update relies on this.
- **Board circuit** (guide AS x4 figures):
  - nCS / MSEL0: 4.7 kΩ pull-up to VCCIO_SDM, because AS_nCSO0 doubles as MSEL0.
  - nCONFIG / nSTATUS: 1–10 kΩ pull-ups to VCCIO_SDM.
  - DQ2 / DQ3: this board copies the Trenz board's 10 kΩ pull-ups to 1.8 V; the guide's figures don't show any.
  - RESET#: wired straight to AS_nRST. The parts below have an internal pull-up on RESET#.
- **Altera's lists:**
  - Tested in the guide (Table 33, for the Parallel Flash Loader II IP): Micron MT25QU256ABA, MT25QU512ABB,
    MT25QU01GBBB, MT25QU02GCBB and Macronix MX66U2G45G.
  - The Device Configuration Support Center keeps a fuller "Supported Third Party Configuration Devices" table
    for Agilex 3/5/7.
  - Other parts meeting the rules above are "generic" flash. They should work, but Altera hasn't tested them.

## Finding a dedicated reset pin in the part number

Reset pins depend on the package and on the exact part number. Check the ball map for every candidate.

| Vendor | Dedicated RESET# | No dedicated RESET# |
|---|---|---|
| Micron MT25Q | Pin-configuration digit (right after the die revision, as in `MT25QU256ABA`**`8`**`E12`) = **3** (RESET#) or **8** (RESET# + HOLD#). On ball A4 in the 24-ball BGA, pin 3 in SOIC-16 | Digit **1** (HOLD# only); 8-pin packages |
| Winbond W25Q..JW | 24-ball TFBGA (package code B = 5×5, C = 4×6), /RESET on A4; SOIC-16 pin 3 | WSON-8, SOIC-8 (only the /HOLD-or-/RESET shared with IO3) |
| ISSI IS25WP | Option letter **R** (or P/T) after the dash, as in `IS25WP256D-`**`R`**`HLE`; H = 5×5 BGA, G = 4×6 BGA | No R/P/T option; any WSON-8 |
| Macronix MX25U / MX66U | Not checked against a datasheet here; some 24-ball BGA and SOIC-16 variants have RESET#, so check the ball map | 8-pin packages |

The 24-ball 6×8 mm BGA in the 5×5 ball array has the same pinout across these vendors, so they can swap on one
footprint:

| Ball | A4 | B2 | B3 | B4 | C2 | C4 | D2 | D3 | D4 |
|---|---|---|---|---|---|---|---|---|---|
| Signal | RESET# | CLK | GND | VCC | CS# | DQ2 | DQ1 | DQ0 | DQ3 |

## Example parts

All are 1.8 V, support SFDP and have a dedicated reset pin; each is checked against its datasheet.

| Part number | Size | Package | Reset pin | LCSC | JLC stock | Notes |
|---|---|---|---|---|---|---|
| MT25QU256ABA8E12-1SIT | 256 Mb | 24-ball BGA 5×5 | A4 | C2061023 | 48 | Altera-tested; used on this board and on the Trenz Agilex 3 board |
| MT25QU01GBBB8E12-0SIT | 1 Gb | 24-ball BGA 5×5 | A4 | C2061873 | 56 | Altera-tested |
| MT25QU256ABA8ESF-0SIT | 256 Mb | SOIC-16 | pin 3 | C2061781 | 200 | Altera-tested family |
| IS25WP256D-RHLE | 256 Mb | 24-ball BGA 5×5 | A4 | C1348936 | 62 | |
| IS25WP128-RHLE | 128 Mb | 24-ball BGA 5×5 | A4 | C1349419 | 68 | |
| IS25WP512M-RHLA3 | 512 Mb | 24-ball BGA 5×5 | A4 | C7211294 | 20 | Automotive grade, −40 to +125 °C |
| W25Q256JWBIQ | 256 Mb | 24-ball BGA 5×5 | A4 | C6000500 | 10 | |
| W25Q128JWBIQ | 128 Mb | 24-ball BGA 5×5 | A4 | C6349614 | 10 | |
| W25Q256JWFIQ TR | 256 Mb | SOIC-16 | pin 3 | C6025200 | 5114 | |

Two more are likely but unconfirmed:
- **W25Q128JWBAQ** (C52993625, 3725 in stock): same 5×5 BGA package code, but LCSC has no datasheet for that
  exact suffix.
- **W25Q512NWFIM TR** (C6604685, SOIC-16, 990 in stock): check its ball map first.

## Unsuitable even though they are 1.8 V QSPI

- Any 8-pin part: WSON-8, SOIC-8 or USON-8, for example W25Q256JWEIQ, GD25LB256EYIGR and MT25QU256ABA1EW9.
  Their reset, if any, is shared with DQ3.
- MT25QU..1E12 (pin-configuration digit 1): the BGA, but HOLD# only, with A4 not connected.
- ISSI parts without the R/P/T option. They have the reset pin only on DQ3.
- W25Q64JW, which was used on v1. Altera doesn't list it as supported.
