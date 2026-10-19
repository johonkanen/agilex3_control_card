# Agilex 3 board requirements (A3CZ065BB18AE7S)

What the FPGA needs from the board: supply rails, I/O bank voltages, power-up order and configuration
pins, and how this card meets each. Device: A3CZ065BB18AE7S. That decodes as 065 density, Z spec (no HPS, crypto,
EMIF, MIPI, PUF or SPDM), B18A package, extended temperature grade, speed grade −7.

Sources, checked 2026-10-16/17:
- Altera *Agilex 3 Device Schematic Review Worksheet* v1.1 (sheets PWR_ref, PWR_CAP, SDM, GPIO, Sensor, DNU_NC);
- *Pin Connection Guidelines* 846812, which Altera still marks Preliminary;
- *Device Configuration User Guide* 847422 (rev. 2026.04.27);
- *Power Management User Guide* 846855, from search summaries only, because the Intel pages redirect in a loop;
- the A3CZ065B B18A pin list (`reference/A3CZ065B_pin_list_B18A.csv`).

The exact min/max voltages are in the *Device Data Sheet* (848370), which I couldn't open; the nominal values below are
the guideline values.

## 1. Supply rails

| Rail | Nominal | Rule | Power group | This card |
|---|---|---|---|---|
| VCC, VCCP | 0.75 V (−7S) | same voltage, plane and regulator as each other | 1 | +0V75 (AP61302, remote sense) |
| VCCL_SDM | **0.75 V for −7S**, 0.78 V for −6S | | 1 | +0V75 |
| VCC_IO_SDM, VCCL_ADC_SDM | as VCC | may share VCC; never float or ground | 1 | +0V75 |
| VCCH_SDM | | to VCCL_SDM on parts without transceivers | 1 | +0V75 |
| VCCPLLDIG_SDM | as VCCL_SDM | same regulator as VCCL_SDM, **with isolation filtering** | 1 | +0V75_PLLDIG (bead + 47 µF + 1 µF) |
| VCCPT | 1.8 V | low-noise switching regulator | 2A | +1V8 (AP61102) |
| VCCPT_HVIO, VCCFUSEWR_SDM | 1.8 V | same regulator as VCCPT | 2A | +1V8 |
| VCCIO_SDM | 1.8 V | may share the VCCPT regulator | 2A | +1V8 |
| VCCPLL_SDM, VCCADC | 1.8 V | from VCCPT **with isolation filtering** | 2A | +1V8_PLL, +1V8_ADC (filtered) |
| VCCRCORE | 1.2 V | may share VCCIO_PIO when that is 1.2 V | 2B | +1V2_RCORE (filtered, from TLV75512) |
| VCCIO_PIO_SDM | | to VCCRCORE unless Avalon-ST x16 configuration is used | 2B | +1V2 |
| VCCIO_PIO_3A_T (HSIO) | 1.0–1.3 V | one of 1.0/1.05/1.1/1.2/1.3 V | 2B | +1V2 (bank unused) |
| VCCIO_HVIO_6A…6H | 1.8, 2.5 or 3.3 V | own regulator ("Isolate") | 2B | +3V3; 6C on its own 1.8 V LDO (`+1V8_HR`) |
| VCCLSENSE / GNDSENSE | | differential remote sense to the core regulator | | VCC_SENSE_P/N pair on L6 |

Decoupling (worksheet PWR_CAP for A3C065 in B18A):
- 2× 4.7 µF on VCC/VCCP;
- 2× 4.7 µF 0201 + 10 µF on VCCPT;
- 1 µF 0201 per SDM rail;
- 1 µF on each filtered rail (plus its LC filter);
- 1–2 µF per HVIO bank.

The card puts 1 µF and 4.7 µF 0201s on supply/ground ball pairs, and bulk caps in the via-free channels.

## 2. I/O bank voltages

| Bank | Allowed I/O voltage | Notes | This card |
|---|---|---|---|
| **SDM** (JTAG, nCONFIG, nSTATUS, MSEL/AS pins, OSC_CLK_1, SDM_IO) | **1.8 V only** | VCCIO_SDM is 1.8 V; nothing at 3.3 V may drive these pins | 1.8 V QSPI flash; JTAG header through an SN74AVC4T774 level shifter |
| HVIO 6A–6H (20 pins each) | 1.8 / 2.5 / 3.3 V LVCMOS/LVTTL, one voltage per bank | a pin can't take an input above its bank's VCCIO; HVIO is single-ended only | 6C = 1.8 V (HyperRAM), 6D = 1.8 V (CLK100M only); other banks 3.3 V |
| HSIO 3A_T (48 pins) | 1.0 / 1.05 / 1.1 / 1.2 / 1.3 V | the LVDS / high-speed I/O | unused |
| HPS I/O | 1.8 V | none on Z-spec parts | — |

- **Dedicated clock inputs:** PLLREFCLK1/2 in each HVIO bank are the clock inputs for the IOPLLs. The card's clock goes into 6D PLLREFCLK1 (D18).
- **No hot socketing:** before power-up, SDM I/O pins tolerate at most 10 mA per pin and 100 mA per bank.

## 3. Power-up order

- **Order:** Group 1 → Group 2A → Group 2B. Each group must reach 90 % of nominal before the next starts.
- **Within a group:** rails may ramp in any order.
- **Ramps:** every rail ramps monotonically, and the sequence must meet the power-on-reset (POR) delay (data sheet).
- **AS normal mode:** VCCIO_SDM must reach its operating level within 10 ms, and the flash must be powered no later than VCCIO_SDM.
- **POR monitoring:** the POR circuit watches VCCL_SDM, VCCPT, VCCIO_SDM, VCCADC, VCC, VCCIO_PIO_SDM, VCCRCORE and VCC_IO_SDM.
- **This card:**
  1. 0.75 V buck (group 1) starts first;
  2. its PG enables the 1.8 V buck (2A); the flash is on the same +1V8;
  3. the 1.8 V PG enables the 3.3 V buck (2B);
  4. the 1.2 V LDO and bank 6C's 1.8 V LDO come up from +3V3 (2B).
- **Bank 6C has its own 1.8 V rail** (fixed 2026-10-17). The Pin Connection Guidelines (846812, 2025.08.13, section 1.5,
  Table 32 and Figure 1) put VCCIO_HVIO in power group 2B on its own regulator (#5, sharing "Isolate": "Connect to a
  dedicated 3.3-V, 2.5-V, 1.8-V power supply"). Only VCCPT_HVIO, VCCIO_SDM, VCCIO_HPS and VCCFUSEWR_SDM may share the
  VCCPT regulator, plus VCCADC, VCCPLL_SDM and VCCPLL_HPS through filters.
  - Supply: `+1V8_HR` from a TLV75518PDBVR (U16) fed from +3V3, so it ramps in group 2B.
  - Loads: VCCIO_HVIO_6C (U17, W15), VCCIO_HVIO_6D (P15, P17), the HyperRAM, and the oscillator through its bead, so
    the oscillator never drives D18 while bank 6D is unpowered. It still starts before power-on reset releases, because the POR circuit watches the
    2B rails VCCRCORE and VCCIO_PIO_SDM.
  - On the board: an L3 island over the HyperRAM, with a strip to the bank balls.

## 4. Configuration (Active Serial x4)

| Item | Requirement | This card |
|---|---|---|
| MSEL[2:0] (SDM_IO9, IO7, IO5) | 011 = AS normal; 001 = AS fast (all rails within 10 ms); 111 = JTAG only; 4.7 kΩ straps | 011: MSEL0 (= AS_nCSO0) and MSEL1 4.7 k up, MSEL2 4.7 k down |
| nCONFIG | 10 kΩ pull-up to VCCIO_SDM; driving it low then high restarts configuration | 10 k |
| nSTATUS | 10 kΩ pull-up to VCCIO_SDM; nothing may pull it low at power-up | 10 k |
| RREF_SDM | 2 kΩ ±1 % to GND | 2 k 1 % |
| OSC_CLK_1 | free-running 25, 100 or 125 MHz, or unconnected (internal oscillator, Quartus default). Required for transceivers/EMIF/MIPI/PHY Lite. With it, the −7 configuration clock is 200 MHz and AS_CLK is limited to 25/50/100 MHz | 100 MHz, fly-by from the same oscillator as B3 |
| AS flash | 1.8 V, SFDP, dedicated RESET# wired only to AS_nRST (SDM_IO15); details in `agilex_flash_requirements.md` | MT25QU256ABA8E12 |
| JTAG | TCK 1 kΩ to GND; TMS/TDI 1–10 kΩ to VCCIO_SDM; all 1.8 V | pulls on the 3.3 V header side of the shifter; internal 20 k pulls on the 1.8 V side |
| SDM_IO0 / SDM_IO16 | optional CONF_DONE / INIT_DONE; internal pull-down | unused |

Quartus settings: configuration scheme Active Serial x4, `DEVICE_INITIALIZATION_CLOCK OSC_CLK_1_100MHZ`,
`ACTIVE_SERIAL_CLOCK AS_FREQ_100MHZ`.

## 5. Pins that must be tied or left open

- **VREFP_ADC, VREFN_ADC:** to GND when no external 1.25 V reference is used.
- **VSIGP_0/1, VSIGN_0/1:** to GND when the voltage sensor is unused.
- **TEMPDIODE pins:** open when unused.
- **DNU:** must float, never to power or GND.
- **NC:** float. The CZ100 powers 10 balls that are NC on the 025/065, so the 100 is not a drop-in.
- **Unused HVIO:** as set in Quartus.
