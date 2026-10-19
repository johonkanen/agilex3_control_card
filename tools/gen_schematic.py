#!/usr/bin/env python3
"""Generate the first-draft schematic for the Agilex 3 control card.

    KICAD_SYMBOL_DIR=.../share/kicad/symbols KICAD_CLI=.../kicad-cli \
        python3 -I tools/gen_schematic.py

Writes hardware/control_card.kicad_sch (root), hardware/sheets/*.kicad_sch,
hardware/lib/control_card.kicad_sym (custom symbols) and reference/pin_assignment.csv.
See docs/design-notes.md for the design decisions behind the circuits.

Reference only: once a sheet has been edited in KiCad, edit it there; rerunning this
overwrites every generated sheet.
"""
import csv
import math
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schgen as sg  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HW = os.path.join(ROOT, "hardware")
REF = os.path.join(ROOT, "reference")
STOCK = os.environ.get("KICAD_SYMBOL_DIR", "")

# ------------------------------------------------------------------ parts (MPN -> LCSC filled by tools/jlc_bom.py)
R0201 = "Resistor_SMD:R_0201_0603Metric"
R0402 = "Resistor_SMD:R_0402_1005Metric"
C0201 = "Capacitor_SMD:C_0201_0603Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
L0806 = "Inductor_SMD:L_Cenker_CKCS201610"

RES = {"0R": "0402WGF0000TCE", "10R": "0402WGF100JTCE", "33R": "0402WGF330JTCE", "100R": "0402WGF1000TCE",
       "1k": "0402WGF1001TCE", "2k": "0402WGF2001TCE", "4k7": "0402WGF4701TCE", "10k": "0402WGF1002TCE",
       "44k2": "0402WGF4422TCE", "49k9": "0402WGF4992TCE", "100k": "0402WGF1003TCE", "200k": "0402WGF2003TCE",
       "1k_0201": "0201WMF1001TEE", "10k_0201": "0201WMF1002TEE"}
CAP = {"22p": ("0402CG220J500NT", C0402), "680p": ("0402CG681J500NT", C0402), "100n": ("CL05B104KO5NNNC", C0402),
       "1u": ("CL05A105KA5NQNC", C0402), "4u7": ("CL10A475KO8NNNC", C0603), "10u": ("CL10A106KP8NNNC", C0603),
       "22u": ("CL10A226MQ8NRNC", C0603), "22u_25V": ("CL21A226MAQNNNE", C0805),
       "47u": ("CGA0603X5R476M6R3JT", C0603), "470n": ("CL05A474KP5NNNC", C0402),
       "100n_0201": ("CL03A104KP3NNNC", C0201), "1u_0201": ("CL03A105MQ3CSNC", C0201),
       "4u7_0201": ("GRM035R60J475ME15D", C0201)}   # "_suffix" selects a variant; the value shown is before "_"
LCSC = {"OT3225100MJBA4SL": "C4353707"}   # name with spaces: not found by exact lookup


def lcsc(mpn):
    return LCSC.get(mpn, "")


# ------------------------------------------------------------------ helpers

class Layout:
    """Left-to-right shelf packing of blocks on a sheet."""
    def __init__(self, x0=25.4, y0=30.48, width=370.0):
        self.x0, self.x, self.y, self.w, self.row_h = x0, x0, y0, width, 0.0

    def slot(self, w, h):
        if self.x + w > self.x0 + self.w and self.x > self.x0:
            self.x, self.y, self.row_h = self.x0, self.y + self.row_h + 7.62, 0.0
        x, y = self.x, self.y
        self.x += w
        self.row_h = max(self.row_h, h)
        return grid(x), grid(y)

    def newline(self):
        if self.row_h:
            self.x, self.y, self.row_h = self.x0, self.y + self.row_h + 7.62, 0.0


def grid(v, g=2.54):
    return sg.rnd(round(v / g) * g)


D = None   # Design


def res(sh, key, value, n1, n2, lay, desc="", dnp=False):
    x, y = lay.slot(12.7, 17.78)
    D.place(sh, key, "Device:R", x + 2.54, y + 7.62, value.split("_")[0], {"1": n1, "2": n2},
            fp=R0201 if value.endswith("_0201") else R0402,
            mpn=RES[value], lcsc=lcsc(RES[value]), desc=desc, dnp=dnp, prefix="R")


def cap(sh, key, value, n1, n2, lay, desc=""):
    mpn, fp = CAP[value]
    x, y = lay.slot(12.7, 17.78)
    D.place(sh, key, "Device:C", x + 2.54, y + 7.62, value.split("_")[0], {"1": n1, "2": n2}, fp=fp,
            mpn=mpn, lcsc=lcsc(mpn), desc=desc, prefix="C")


BEAD = ("BLM18PG121SN1D", "Inductor_SMD:L_0603_1608Metric")   # 120 R @ 100 MHz, 2 A, JLC basic


def bead(sh, key, n1, n2, lay, desc=""):
    x, y = lay.slot(7.62, 12.7)
    D.place(sh, key, "Device:FerriteBead", x + 2.54, y + 7.62, "120R@100MHz", {"1": n1, "2": n2}, fp=BEAD[1],
            mpn=BEAD[0], lcsc=lcsc(BEAD[0]), desc=desc, prefix="FB")


def pdn_filter(sh, key, src, dst, lay, desc):
    """Isolation filter for a sensitive FPGA supply, as on the AXC3000 (TEI0131): bead, then 47 uF + 1 uF (0201 at the ball)."""
    bead(sh, f"FB_{key}", src, dst, lay, desc)
    cap(sh, f"C_{key}_b", "47u", dst, "GND", lay)
    cap(sh, f"C_{key}_h", "1u_0201", dst, "GND", lay)


def caps(sh, key, spec, n1, n2, lay, desc=""):
    """spec: list of (value, count)."""
    i = 0
    for value, count in spec:
        for _ in range(count):
            cap(sh, f"{key}{i}", value, n1, n2, lay, desc)
            i += 1


def ic(sh, key, lib_id, lay, value, nets, unit=1, fp=None, mpn="", desc="", ds="", ref_key=None, prefix="U"):
    sym = D.libs[lib_id]
    pins = sym.unit_pins(unit)
    bx0, by0, bx1, by1 = sym.unit_bbox(unit)

    def lab(n):
        return 0 if not n else len(n) * 1.27 + 5.08
    # pins pointing right (angle 0) sit on the left edge and carry their labels to the left
    lw = max([lab(nets.get(k)) for k, p in pins.items() if p["angle"] == 0] + [0])
    rw = max([lab(nets.get(k)) for k, p in pins.items() if p["angle"] == 180] + [0])
    w = (bx1 - bx0) + lw + rw + 10.16
    h = (by1 - by0) + 15.24
    x, y = lay.slot(w, h)
    X = grid(x + lw - bx0 + 2.54)
    Y = grid(y + by1 + 7.62)
    return D.place(sh, key, lib_id, X, Y, value, nets, unit=unit, fp=fp, mpn=mpn, lcsc=lcsc(mpn), desc=desc,
                   ds=ds, ref_key=ref_key, prefix=prefix)


# ------------------------------------------------------------------ custom symbols

def custom_symbols():
    B = sg.box_symbol
    syms = [
        B("ADS7056", [("AVDD", "6", "power_in"), ("AINP", "7", "input"), ("AINM", "8", "input"), None,
                      ("GND", "5", "power_in")],
          [("DVDD", "4", "power_in"), ("~{CS}", "1", "input"), ("SCLK", "3", "input"), ("SDO", "2", "output")],
          footprint="Package_DFN_QFN:Texas_UQFN-8_1.5x1.5mm_P0.5mm",
          desc="14-bit 2.5 MSPS SAR ADC, X2QFN-8 (RUG)", datasheet="https://www.ti.com/lit/ds/symlink/ads7056.pdf"),
        B("SN74AXC4T774RSV",
          [("VCCA", "14", "power_in"), ("DIR1", "15", "input"), ("DIR2", "16", "input"), ("DIR3", "5", "input"),
           ("DIR4", "6", "input"), ("~{OE}", "7", "input"), ("A1", "1", "bidirectional"), ("A2", "2", "bidirectional"),
           ("A3", "3", "bidirectional"), ("A4", "4", "bidirectional"), ("GND", "8", "power_in")],
          [("VCCB", "13", "power_in"), None, None, None, None, None, ("B1", "12", "bidirectional"),
           ("B2", "11", "bidirectional"), ("B3", "10", "bidirectional"), ("B4", "9", "bidirectional")],
          footprint="Package_DFN_QFN:UQFN-16_1.8x2.6mm_P0.4mm",
          desc="4-bit dual-supply translator, DIRx/OE referenced to VCCA. DIR=H: A to B.",
          datasheet="https://www.ti.com/lit/ds/symlink/sn74axc4t774.pdf"),
        B("W958D8NBYA",
          [("CK", "B2", "input"), ("~{CK}", "B1", "input"), ("~{CS}", "A3", "input"), ("~{RESET}", "A4", "input"),
           ("RWDS", "C3", "bidirectional"), None, ("VCC", "B4", "power_in"), ("VCCQ", "D1", "power_in"),
           ("VCCQ", "E4", "power_in"), ("VSS", "B3", "power_in"), ("VSSQ", "C1", "power_in"),
           ("VSSQ", "E5", "power_in")],
          [("DQ0", "D3", "bidirectional"), ("DQ1", "D2", "bidirectional"), ("DQ2", "C4", "bidirectional"),
           ("DQ3", "D4", "bidirectional"), ("DQ4", "D5", "bidirectional"), ("DQ5", "E3", "bidirectional"),
           ("DQ6", "E2", "bidirectional"), ("DQ7", "E1", "bidirectional"), None, ("RFU", "A2", "no_connect"),
           ("RFU", "A5", "no_connect"), ("RFU", "B5", "no_connect"), ("RFU", "C2", "no_connect"),
           ("RFU", "C5", "no_connect")],
          footprint="control_card:BGA-24_6x8mm_Layout5x5_P1.0mm_CY0.5",
          desc="256 Mb HyperRAM, 1.8 V, 200 MHz. Standard 24-ball HyperBus pinout; CK# unused (single-ended CK is the default).",
          datasheet="https://www.winbond.com/hq/support/documentation/levelOne.jsp?__locale=en&DocNo=DA00-W958D8NBYA.3"),
        B("MT25QU256ABA8E12",
          [("~{S}", "C2", "input"), ("C", "B2", "input"), ("~{RESET}", "A4", "input"), ("DQ0", "D3", "bidirectional"),
           ("DQ1", "D2", "bidirectional"), ("~{W}/DQ2", "C4", "bidirectional"),
           ("~{HOLD}/DQ3", "D4", "bidirectional"), None, ("VCC", "B4", "power_in"), ("VSS", "B3", "power_in")],
          [("NC", b, "no_connect") for b in ("A2", "A3", "A5", "B1", "B5", "C1", "C3", "C5", "D1", "D5",
                                              "E1", "E2", "E3", "E4", "E5")],
          footprint="control_card:BGA-24_6x8mm_Layout5x5_P1.0mm_CY0.5",
          desc="256 Mb 1.8 V QSPI NOR, TPBGA-24 (as on the Trenz Agilex 3 board)",
          datasheet="https://www.micron.com/products/storage/nor-flash/serial-nor/part-catalog/mt25qu256aba8e12-1sit"),
        B("LED_RGB_CA", [("A", "2", "passive")],
          [("RK", "1", "passive"), ("GK", "3", "passive"), ("BK", "4", "passive")], ref="D",
          footprint="control_card:LED_RGB_APFA3010_RightAngle",
          desc="Right-angle common-anode RGB LED APFA3010LSEEZGKQBKC (as on U25): 2 = anode, 1 = red, 3 = green, 4 = blue cathode",
          datasheet="https://wmsc.lcsc.com/wmsc/upload/file/pdf/v2/lcsc/2306061206_Kingbright-APFA3010LSEEZGKQBKC_C5393554.pdf"),
    ]
    path = os.path.join(HW, "lib", "control_card.kicad_sym")
    sg.write_symbol_lib(path, syms)
    for name in ("ADS7056", "SN74AXC4T774RSV", "W958D8NBYA", "LED_RGB_CA", "MT25QU256ABA8E12"):
        D.file_symbol(f"control_card:{name}", path, name)


# ------------------------------------------------------------------ FPGA pin assignment

FPGA = "agilex3:A3CY025B-B18A"   # symbol from the 025 pin list; the A3CZ065B's B18A ball map is identical (reference/A3CZ065B_pin_list_B18A.csv)


def fpga_balls():
    fp = open(os.path.join(HW, "lib", "control_card.pretty", "Altera_B18A.kicad_mod")).read()
    return {m.group(1): (float(m.group(2)), float(m.group(3)))
            for m in re.finditer(r'\(pad "(\w+)" smd circle\s+\(at ([-\d.]+) ([-\d.]+)\)', fp)}


def header_rows():
    return list(csv.DictReader(open(os.path.join(REF, "power_board_header.csv"))))


def header_net(r):
    if r["dir_from_fpga"] in ("power", "analog"):
        return {"5V": "+5V", "DGND": "GND"}.get(r["signal"], r["signal"])
    return r["signal"] or f"J1_P{r['card_pin']}"


def assign_pins():
    sym = D.libs[FPGA]
    pos = fpga_balls()
    banks = {}
    for num, p in sym.pins.items():
        m = re.match(r"(6[A-H])_IO_HVIO_\w+?_(\d+)_", p["name"])
        if m:
            banks.setdefault(m.group(1), []).append(num)
    # outer balls first: shorter escape routes
    for b in banks:
        banks[b].sort(key=lambda n: -max(abs(pos[n][0]), abs(pos[n][1])))
    hdr = [r for r in header_rows() if r["dir_from_fpga"] in ("in", "out", "spare")]
    hdr.sort(key=lambda r: (r["dir_from_fpga"] == "spare", int(r["card_pin"])))
    want = {"6A": [], "6B": []}
    for i, r in enumerate(hdr):
        want["6A" if i % 2 == 0 else "6B"].append((header_net(r), r["dir_from_fpga"], f"J1 pin {r['card_pin']}"))
    want["6C"] = [(n, "io", "HyperRAM") for n in
                  ["HR_CK", "HR_CS_N", "HR_RESET_N", "HR_RWDS"] + [f"HR_DQ{i}" for i in range(8)]]
    # the 1.8 V 100 MHz oscillator: PLL reference clock in the 1.8 V bank, fly-by on to OSC_CLK_1
    # the 1.8 V 100 MHz oscillator: PLLREFCLK1 of bank 6D (D18, outer edge), which otherwise carries nothing and runs at
    # 1.8 V from +1V8_HR; 6C's PLLREFCLK2 (B3) could not be routed (HyperRAM traces on L1, the 1.8 V buck under it on L6)
    want["6G"] = [(n, d, "ADC A") for n, d in
                  (("ADCA_CS_N", "out"), ("ADCA_SCLK", "out"), ("ADCA_SDO", "in"),
                   ("ADASEL0", "out"), ("ADASEL1", "out"), ("ADASEL2", "out"))]
    want["6H"] = [(n, d, "ADC B") for n, d in
                  (("ADCB_CS_N", "out"), ("ADCB_SCLK", "out"), ("ADCB_SDO", "in"),
                   ("ADBSEL0", "out"), ("ADBSEL1", "out"), ("ADBSEL2", "out"))]
    want["6D"] = [("CLK100M", "in", "100 MHz oscillator (also SDM OSC_CLK_1)")]
    want["6H"] += [(f"LED{k}_{c}", "out", "RGB LED") for k in (1, 2) for c in "RGB"]
    # reference/io_assignment.csv (from tools/assign_io.py, placement-driven) overrides the bank plan
    fixed = {}
    io_file = os.path.join(REF, "io_assignment.csv")
    if os.path.exists(io_file):
        fixed = {r["net"]: r["ball"] for r in csv.DictReader(open(io_file))}
    used = set(fixed.values())
    assign = {}
    rows = []
    for bank, sigs in want.items():
        free = [b for b in banks[bank] if b not in used]
        for net, d, use in sigs:
            if net in fixed:
                ball = fixed[net]
                if not re.match(r"6[A-H]_IO_HVIO", sym.pins[ball]["name"]):
                    raise SystemExit(f"{net}: ball {ball} is not an HVIO pin")
            elif net == "CLK100M":   # dedicated PLL reference clock input
                ball = next(n for n in free if "PLLREFCLK1" in sym.pins[n]["name"])
            else:
                ball = free[0]
            if ball in free:
                free.remove(ball)
            if ball in assign:
                raise SystemExit(f"ball {ball} assigned twice ({assign[ball]}, {net})")
            assign[ball] = net
            rows.append(dict(net=net, ball=ball, bank=sym.pins[ball]["name"][:2], dir=d, use=use,
                             pin_name=sym.pins[ball]["name"]))
    with open(os.path.join(REF, "pin_assignment.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["net", "ball", "bank", "dir", "use", "pin_name"])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["bank"], r["net"])))
    return assign


def fpga_net(name, ball, assign):
    """Net for every non-HVIO-signal FPGA pin; None = no-connect."""
    if ball in assign:
        return assign[ball]
    rails = {
        "+0V75": ("VCC", "VCCP", "VCCL_SDM", "VCCH_SDM", "VCC_IO_SDM", "VCCL_ADC_SDM"),
        "+1V8": ("VCCPT", "VCCPT_HVIO", "VCCIO_SDM", "VCCFUSEWR_SDM"),
        "+1V2": ("VCCIO_PIO_3A_T", "VCCIO_PIO_SDM"),
        # filtered from those rails (Altera pin guidelines: "with proper isolation filtering"; AXC3000 also
        # filters VCCRCORE): see the decoupling sheet
        "+0V75_PLLDIG": ("VCCPLLDIG_SDM",), "+1V8_PLL": ("VCCPLL_SDM",), "+1V8_ADC": ("VCCADC",),
        "+1V2_RCORE": ("VCCRCORE",),
    }
    for net, names in rails.items():
        if name in names:
            return net
    if name.startswith(("VCCIO_HVIO_6C", "VCCIO_HVIO_6D")):
        return "+1V8_HR"   # banks 6C (HyperRAM) and 6D (clock) at 1.8 V from their own LDO
    if name.startswith("VCCIO_HVIO_"):
        return "+3V3"
    if name == "GND":
        return "GND"
    sdm = {
        "SDM_TCK": "TCK_1V8", "SDM_TDI": "TDI_1V8", "SDM_TMS": "TMS_1V8", "SDM_TDO": "TDO_1V8",
        "SDM_nCONFIG": "NCONFIG", "SDM_nSTATUS": "NSTATUS", "SDM_RREF_SDM": "RREF_SDM",
        "SDM_SDM_IO2_AVSTx8_DATA0_AS_CLK": "AS_CLK", "SDM_SDM_IO4_AVSTx8_DATA1_AS_DATA0": "AS_DATA0",
        "SDM_SDM_IO1_AVSTx8_DATA2_AS_DATA1": "AS_DATA1", "SDM_SDM_IO3_AVSTx8_DATA3_AS_DATA2": "AS_DATA2",
        "SDM_SDM_IO6_AVSTx8_DATA4_AS_DATA3": "AS_DATA3", "SDM_SDM_IO5_AS_nCSO0_MSEL0": "AS_NCS_MSEL0",
        "SDM_SDM_IO7_AS_nCSO2_MSEL1": "MSEL1", "SDM_SDM_IO9_AS_nCSO1_MSEL2": "MSEL2",
        "SDM_SDM_IO15_AVSTx8_DATA6_AS_nRST": "AS_NRST",
        "SDM_OSC_CLK_1": "CLK100M",   # configuration clock: a second branch from the oscillator's 33R, beside PLLREFCLK1 (D18)
                "SDM_VREFP_ADC": "GND", "SDM_VREFN_ADC": "GND", "SDM_VSIGP_0": "GND", "SDM_VSIGN_0": "GND",
        "SDM_VSIGP_1": "GND", "SDM_VSIGN_1": "GND",
        "VCCLSENSE": "VCC_SENSE_P", "GNDSENSE": "VCC_SENSE_N",
    }
    return sdm.get(name)


# ------------------------------------------------------------------ sheets

def sheet_power():
    sh = sg.Sheet("Power", "sheets/power.kicad_sch", "A3", "Power: 5 V in, 0.75/1.8/3.3 V bucks, 1.2 V and analog 3.3 V LDOs")
    D.sheets.append(sh)
    lay = Layout()
    sh.text("Power-up order (proven on agilex3_control_card_v1): 0.75 V -> PG -> 1.8 V -> PG -> 3.3 V and 1.2 V.\n"
            "Buck FB reference 0.6 V: Vout = 0.6 x (1 + Rtop/Rbot). AP61102/AP61302 pinout: FB, GND, VIN, SW, EN, PG.\n"
            "Core divider top sits on VCC_SENSE_P (FPGA VCCLSENSE ball, remote sense); 100R from +0V75 keeps regulation if open.",
            25.4, 15.24)
    buck = "Regulator_Switching:AP61202Z6"
    # 0.75 V core, 3 A
    D.group = "buck_core"
    ic(sh, "U_core", buck, lay, "AP61302Z6-7", {"3": "+5V", "5": "+5V", "4": "SW_0V75", "1": "FB_0V75",
       "2": "GND", "6": "PG_0V75"}, mpn="AP61302Z6-7", desc="0.75 V core buck, 3 A, PG",
       ds="https://www.diodes.com/assets/Datasheets/AP61300_AP61302.pdf")
    D.place(sh, "L_core", "Device:L", *lay.slot(12.7, 17.78), "1u", {"1": "SW_0V75", "2": "+0V75"}, fp=L0806,
            mpn="WPN201610H1R0MT", lcsc=lcsc("WPN201610H1R0MT"), prefix="L")
    res(sh, "R_core_t", "49k9", "VCC_SENSE_P", "FB_0V75", lay, "0.6 x (1 + 49.9k/200k) = 0.750 V")
    res(sh, "R_core_b", "200k", "FB_0V75", "VCC_SENSE_N", lay)
    res(sh, "R_core_loc", "100R", "+0V75", "VCC_SENSE_P", lay, "Local sense fallback")
    res(sh, "R_core_gnd", "10R", "VCC_SENSE_N", "GND", lay, "Local ground-sense fallback")
    res(sh, "R_pg0", "100k", "+5V", "PG_0V75", lay, "PG pull-up")
    cap(sh, "C_core_in", "10u", "+5V", "GND", lay)
    caps(sh, "C_core_out", [("22u", 2)], "+0V75", "GND", lay)
    lay.newline()
    # 1.8 V
    D.group = "buck_1v8"
    ic(sh, "U_1v8", buck, lay, "AP61102Z6-7", {"3": "+5V", "5": "PG_0V75", "4": "SW_1V8", "1": "FB_1V8",
       "2": "GND", "6": "PG_1V8"}, mpn="AP61102Z6-7", desc="1.8 V buck, 1 A, PG. Enabled by core PG.",
       ds="https://www.diodes.com/assets/Datasheets/AP61100_AP61102.pdf")
    D.place(sh, "L_1v8", "Device:L", *lay.slot(12.7, 17.78), "1u", {"1": "SW_1V8", "2": "+1V8"}, fp=L0806,
            mpn="WPN201610H1R0MT", lcsc=lcsc("WPN201610H1R0MT"), prefix="L")
    res(sh, "R_1v8_t", "200k", "+1V8", "FB_1V8", lay, "0.6 x (1 + 200k/100k) = 1.80 V")
    res(sh, "R_1v8_b", "100k", "FB_1V8", "GND", lay)
    cap(sh, "C_1v8_ff", "22p", "+1V8", "FB_1V8", lay, "Feed-forward")
    res(sh, "R_pg1", "100k", "+5V", "PG_1V8", lay, "PG pull-up")
    cap(sh, "C_1v8_in", "10u", "+5V", "GND", lay)
    caps(sh, "C_1v8_out", [("22u", 1)], "+1V8", "GND", lay)
    lay.newline()
    # 3.3 V
    D.group = "buck_3v3"
    ic(sh, "U_3v3", buck, lay, "AP61102Z6-7", {"3": "+5V", "5": "PG_1V8", "4": "SW_3V3", "1": "FB_3V3",
       "2": "GND", "6": None}, mpn="AP61102Z6-7", desc="3.3 V buck, 1 A. Enabled by 1.8 V PG.",
       ds="https://www.diodes.com/assets/Datasheets/AP61100_AP61102.pdf")
    D.place(sh, "L_3v3", "Device:L", *lay.slot(12.7, 17.78), "1u", {"1": "SW_3V3", "2": "+3V3"}, fp=L0806,
            mpn="WPN201610H1R0MT", lcsc=lcsc("WPN201610H1R0MT"), prefix="L")
    res(sh, "R_3v3_t", "200k", "+3V3", "FB_3V3", lay, "0.6 x (1 + 200k/44.2k) = 3.31 V")
    res(sh, "R_3v3_b", "44k2", "FB_3V3", "GND", lay)
    cap(sh, "C_3v3_ff", "22p", "+3V3", "FB_3V3", lay, "Feed-forward")
    cap(sh, "C_3v3_in", "10u", "+5V", "GND", lay)
    caps(sh, "C_3v3_out", [("22u", 1)], "+3V3", "GND", lay)
    lay.newline()
    # 1.2 V LDO from 3.3 V, comes up with 3.3 V
    D.group = "ldo_1v2"
    ldo = "Regulator_Linear:TLV75512PDBV"
    ic(sh, "U_1v2", ldo, lay, "TLV75512PDBVR", {"1": "+3V3", "3": "+3V3", "2": "GND", "4": None, "5": "+1V2"},
       mpn="TLV75512PDBVR", desc="1.2 V for VCCIO_PIO, VCCIO_PIO_SDM, VCCRCORE")
    cap(sh, "C_1v2_in", "1u", "+3V3", "GND", lay)
    cap(sh, "C_1v2_out", "4u7", "+1V2", "GND", lay)
    # 1.8 V for HVIO bank 6C, the HyperRAM and the oscillator, from 3.3 V: Altera's power sharing table (Pin Connection
    # Guidelines 846812 sec. 1.5) gives VCCIO_HVIO its own regulator in power group 2B, so not the VCCPT/VCCIO_SDM rail
    D.group = "ldo_1v8hr"
    ic(sh, "U_1v8hr", "Regulator_Linear:TLV75518PDBV", lay, "TLV75518PDBVR",
       {"1": "+3V3", "3": "+3V3", "2": "GND", "4": None, "5": "+1V8_HR"},
       mpn="TLV75518PDBVR", desc="1.8 V for VCCIO_HVIO_6C/6D, HyperRAM and oscillator (group 2B, isolated)")
    cap(sh, "C_1v8hr_in", "1u", "+3V3", "GND", lay)
    cap(sh, "C_1v8hr_out", "4u7", "+1V8_HR", "GND", lay)
    # analog 3.3 V
    D.group = "ldo_analog"
    ic(sh, "U_3v3a", "Regulator_Linear:TLV75533PDBV", lay, "TLV75533PDBVR",
       {"1": "+5V", "3": "+5V", "2": "GND", "4": None, "5": "+3V3A"}, mpn="TLV75533PDBVR",
       desc="Analog 3.3 V: muxes, buffers, ADC AVDD (full scale 0..3.3 V)")
    cap(sh, "C_3v3a_in", "1u", "+5V", "GND", lay)
    cap(sh, "C_3v3a_out", "1u", "+3V3A", "GND", lay)
    lay.newline()
    # 5 V input bulk, grounds, flags
    D.group = "input_5v"
    caps(sh, "C_5v", [("22u_25V", 2), ("100n", 1)], "+5V", "GND", lay, "5 V input from J1")
    for i, net in enumerate(("+5V", "GND", "+0V75", "+1V8", "+3V3", "VCC_SENSE_P", "VCC_SENSE_N",
                             "+0V75_PLLDIG", "+1V8_PLL", "+1V8_ADC", "+1V2_RCORE", "+1V8_OSC")):   # bead-filtered rails
        D.place(sh, f"FLG{i}", "power:PWR_FLAG", *lay.slot(15.24, 12.7), "PWR_FLAG", {"1": net}, fp="",
                prefix="#FLG", in_bom=False)


def sheet_fpga_power(assign):
    sh = sg.Sheet("FPGA power", "sheets/fpga_power.kicad_sch", "A2", "FPGA supplies, ground and decoupling")
    D.sheets.append(sh)
    lay = Layout(width=540)
    sym = D.libs[FPGA]
    D.group = "fpga"
    for unit in (13, 11, 12):
        nets = {n: fpga_net(p["name"], n, assign) for n, p in sym.unit_pins(unit).items()}
        ic(sh, f"U_fpga_{unit}", FPGA, lay, "A3CZ065BB18AE7S", nets, unit=unit,
           fp="control_card:Altera_B18A", mpn="A3CZ065BB18AE7S", ref_key="FPGA")
    lay.newline()
    sh.text("Decoupling per Altera's Agilex 3 schematic review worksheet (v1.1, PWR_CAP) and the AXC3000: 1 uF / 4.7 uF "
            "0201 on supply/GND ball pairs under the BGA (via-in-pad; counts are what the ball map holds), bulk 0603 in the "
            "via-free channels. VCCPLLDIG_SDM, VCCPLL_SDM, VCCADC and VCCRCORE each get a bead + 47 uF + 1 uF filter.", 25.4, lay.y)
    lay.y += 7.62
    D.group = "decap_0v75"
    caps(sh, "C_0v75_", [("22u", 2), ("10u", 2), ("4u7_0201", 3), ("1u_0201", 5)], "+0V75", "GND", lay,
         "VCC/VCCP 4.7u; VCCL_SDM, VCCH_SDM, VCC_IO_SDM, VCCL_ADC_SDM 1u")
    lay.newline()
    D.group = "decap_1v8"
    caps(sh, "C_1v8_", [("10u", 1), ("4u7_0201", 2), ("1u_0201", 5)], "+1V8", "GND", lay,
         "VCCPT 4.7u; VCCIO_SDM, VCCFUSEWR_SDM, VCCPT_HVIO 1u")
    D.group = "decap_3v3"
    caps(sh, "C_3v3_", [("10u", 1), ("1u_0201", 6)], "+3V3", "GND", lay, "VCCIO_HVIO 6A/6B/6E-6H 1u (6C/6D are 1.8 V)")
    lay.newline()
    D.group = "decap_1v2"
    caps(sh, "C_1v2_", [("4u7", 1), ("4u7_0201", 1), ("1u_0201", 1)], "+1V2", "GND", lay, "VCCIO_PIO_3A_T 4.7u, VCCIO_PIO_SDM 1u")
    lay.newline()
    D.group = "decap_filt"
    pdn_filter(sh, "plldig", "+0V75", "+0V75_PLLDIG", lay, "VCCPLLDIG_SDM filter")
    pdn_filter(sh, "pll", "+1V8", "+1V8_PLL", lay, "VCCPLL_SDM filter")
    pdn_filter(sh, "adc", "+1V8", "+1V8_ADC", lay, "VCCADC filter")
    pdn_filter(sh, "rcore", "+1V2", "+1V2_RCORE", lay, "VCCRCORE filter")
    cap(sh, "C_6c", "1u_0201", "+1V8_HR", "GND", lay, "VCCIO_HVIO_6C")
    cap(sh, "C_6d", "1u_0201", "+1V8_HR", "GND", lay, "VCCIO_HVIO_6D")


def sheet_fpga_io(assign):
    sh = sg.Sheet("FPGA I/O", "sheets/fpga_io.kicad_sch", "A1", "FPGA I/O banks (pin assignment: reference/pin_assignment.csv)")
    D.sheets.append(sh)
    lay = Layout(width=780)
    sym = D.libs[FPGA]
    D.group = "fpga"
    for unit in range(2, 11):
        nets = {n: fpga_net(p["name"], n, assign) for n, p in sym.unit_pins(unit).items()}
        ic(sh, f"U_fpga_{unit}", FPGA, lay, "A3CZ065BB18AE7S", nets, unit=unit,
           fp="control_card:Altera_B18A", mpn="A3CZ065BB18AE7S", ref_key="FPGA")


def sheet_config(assign):
    sh = sg.Sheet("Configuration", "sheets/config.kicad_sch", "A3", "SDM: AS x4 flash, MSEL, JTAG")
    D.sheets.append(sh)
    lay = Layout()
    sym = D.libs[FPGA]
    nets = {n: fpga_net(p["name"], n, assign) for n, p in sym.unit_pins(1).items()}
    D.group = "fpga"
    ic(sh, "U_fpga_1", FPGA, lay, "A3CZ065BB18AE7S", nets, unit=1, fp="control_card:Altera_B18A",
       mpn="A3CZ065BB18AE7S", ref_key="FPGA")
    sh.text("MSEL[2:0] = 011: AS x4 Normal (Fast mode needs all rails up within its ramp window).\n"
            "MT25QU256 as on the Trenz Agilex 3 board: CS 4.7k and DQ2/DQ3 10k pull-ups to 1.8 V.\n"
            "Flash RESET# (A4, internal pull-up) on AS_nRST (SDM_IO15): required for AS x4 (config guide 3.2.7.1).\n"
            "JTAG: J2 is 3.3 V (FTDI mini-module on flying leads), shifted to the 1.8 V SDM.",
            lay.x, lay.y)
    lay.newline()
    D.group = "flash"
    nets = {"C2": "AS_NCS_MSEL0", "B2": "AS_CLK", "D3": "AS_DATA0", "D2": "AS_DATA1", "C4": "AS_DATA2",
            "D4": "AS_DATA3", "A4": "AS_NRST", "B4": "+1V8", "B3": "GND"}
    nets.update({b: None for b in ("A2", "A3", "A5", "B1", "B5", "C1", "C3", "C5", "D1", "D5",
                                   "E1", "E2", "E3", "E4", "E5")})
    ic(sh, "U_flash", "control_card:MT25QU256ABA8E12", lay, "MT25QU256ABA8E12-1SIT", nets,
       mpn="MT25QU256ABA8E12-1SIT", desc="256 Mb 1.8 V QSPI config flash, BGA (as on the Trenz Agilex 3 board)")
    D.group = "flash_decap"   # bottom side, on the flash's VCC/VSS ball pair
    cap(sh, "C_fl0", "100n", "+1V8", "GND", lay)
    cap(sh, "C_fl1", "1u", "+1V8", "GND", lay)
    D.group = "config"        # flash pull-ups: bottom side, under the flash
    res(sh, "R_msel0", "4k7", "+1V8", "AS_NCS_MSEL0", lay, "MSEL0 = 1, flash CS idle high")
    res(sh, "R_msel1", "4k7", "+1V8", "MSEL1", lay, "MSEL1 = 1")
    res(sh, "R_msel2", "4k7", "MSEL2", "GND", lay, "MSEL2 = 0 (AS Normal)")
    res(sh, "R_msel2u", "4k7", "+1V8", "MSEL2", lay, "Fit instead of the pull-down for AS Fast (001 -> 101 n/a)", dnp=True)
    res(sh, "R_d2", "10k", "+1V8", "AS_DATA2", lay)
    res(sh, "R_d3", "10k", "+1V8", "AS_DATA3", lay)
    D.group = "config"
    res(sh, "R_ncfg", "10k", "+1V8", "NCONFIG", lay, "10k to VCCIO_SDM (pin guidelines)")
    res(sh, "R_nst", "10k", "+1V8", "NSTATUS", lay, "10k to VCCIO_SDM (pin guidelines)")
    res(sh, "R_rref", "2k", "RREF_SDM", "GND", lay, "RREF_SDM, 1 %")
    lay.newline()
    D.group = "jtag"          # bottom side under the FPGA, in the unused HSIO area next to the SDM
    # SN74AVC4T774RSVR: same RSV pinout as the AXC symbol (TI datasheets SCES898C / SN74AVC4T774, Table 4-1); the
    # AXC4T774RSVR went out of stock at JLC on 2026-10-16
    ic(sh, "U_jtag", "control_card:SN74AXC4T774RSV", lay, "SN74AVC4T774RSVR",
       {"14": "+3V3", "13": "+1V8", "15": "+3V3", "16": "+3V3", "5": "+3V3", "6": "GND", "7": "GND",
        "1": "TCK", "2": "TDI", "3": "TMS", "4": "TDO", "12": "TCK_1V8", "11": "TDI_1V8", "10": "TMS_1V8",
        "9": "TDO_1V8", "8": "GND"}, mpn="SN74AVC4T774RSVR", desc="JTAG 3.3 V <-> 1.8 V: TCK/TDI/TMS A->B, TDO B->A")
    cap(sh, "C_jt_a", "100n_0201", "+3V3", "GND", lay)
    cap(sh, "C_jt_b", "100n_0201", "+1V8", "GND", lay)
    res(sh, "R_tck", "1k_0201", "TCK", "GND", lay, "TCK pull-down")
    res(sh, "R_tms", "10k_0201", "+3V3", "TMS", lay)
    res(sh, "R_tdi", "10k_0201", "+3V3", "TDI", lay)
    res(sh, "R_tdo", "10k_0201", "+1V8", "TDO_1V8", lay, "Keeps B4 defined while TDO is tri-stated")
    D.group = "jtag_header"
    ic(sh, "J_jtag", "Connector_Generic:Conn_01x05", lay, "JTAG",
       {"1": "TCK", "2": "TDI", "3": "TMS", "4": "TDO", "5": "GND"},
       fp="Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical", prefix="J",
       desc="To FTDI mini-module on flying leads; order is free")


def sheet_memory():
    sh = sg.Sheet("HyperRAM and clock", "sheets/memory.kicad_sch", "A3", "HyperRAM (1.8 V) and 100 MHz oscillator")
    D.sheets.append(sh)
    lay = Layout()
    nets = {"B2": "HR_CK", "B1": None, "A3": "HR_CS_N", "A4": "HR_RESET_N", "C3": "HR_RWDS",
            "B4": "+1V8_HR", "D1": "+1V8_HR", "E4": "+1V8_HR", "B3": "GND", "C1": "GND", "E5": "GND",
            "A2": None, "A5": None, "B5": None, "C2": None, "C5": None}
    nets.update({b: f"HR_DQ{i}" for i, b in enumerate(("D3", "D2", "C4", "D4", "D5", "E3", "E2", "E1"))})
    D.group = "hyperram"
    ic(sh, "U_hram", "control_card:W958D8NBYA", lay, "W958D8NBYA5I", nets,
       mpn="W958D8NBYA5I", desc="32 MB 1.8 V HyperRAM on bank 6C (VCCIO 1.8 V); CK# unused, single-ended clock (CR1[6] default)")
    D.group = "hyperram_decap"   # bottom side, one cap per VCC(Q)/VSS(Q) ball pair
    caps(sh, "C_hr", [("100n", 2), ("1u", 1)], "+1V8_HR", "GND", lay)
    D.group = "hyperram"
    res(sh, "R_hr_rst", "10k", "+1V8_HR", "HR_RESET_N", lay)
    lay.newline()
    D.group = "osc"
    bead(sh, "FB_osc", "+1V8_HR", "+1V8_OSC", lay, "Oscillator supply filter (as AXC3000); on bank 6C's rail, so it never drives B3 unpowered")
    ic(sh, "X_osc", "Oscillator:ASE-xxxMHz", lay, "100MHz", {"1": "+1V8_OSC", "2": "GND", "3": "CLK100M_R", "4": "+1V8_OSC"},
       fp="Oscillator:Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm", mpn="OT3225100MJBA4SL",
       prefix="X", desc="100 MHz 1.8 V CMOS oscillator, 3225: PLLREFCLK2 (B3, bank 6C) and fly-by on to OSC_CLK_1 (BB44)")
    res(sh, "R_osc", "33R", "CLK100M_R", "CLK100M", lay, "Series termination at the source of the fly-by")
    cap(sh, "C_osc", "470n", "+1V8_OSC", "GND", lay)


def adc_chain(sh, lay, ch, inputs):
    """ch: 'A' or 'B'. inputs: mux X0..X7 nets (U25 mapping)."""
    mux = f"MUX{ch}_OUT"
    buf = f"BUF{ch}_OUT"
    ainp = f"AINP_{ch}"
    avdd = "+3V3A"   # buffer and ADC AVDD straight from the analog LDO, no filter bead (U25 had 22 uH per chain)
    sel = "ADASEL" if ch == "A" else "ADBSEL"
    D.group = f"adc_{ch.lower()}"
    nets = {"13": inputs[0], "14": inputs[1], "15": inputs[2], "12": inputs[3], "1": inputs[4], "5": inputs[5],
            "2": inputs[6], "4": inputs[7], "11": f"{sel}0", "10": f"{sel}1", "9": f"{sel}2", "6": "GND",
            "7": "GND", "8": "GND", "16": "+3V3A", "3": mux}
    ic(sh, f"U_mux{ch}", "74xx:74HC4051", lay, "SN74LV4051APWR", nets, fp="Package_SO:TSSOP-16_4.4x5mm_P0.65mm",
       mpn="SN74LV4051APWR", desc=f"ADC {ch} input mux; one input grounded as a zero reference")
    cap(sh, f"C_mux{ch}", "1u", "+3V3A", "GND", lay)
    ic(sh, f"U_buf{ch}", "Amplifier_Operational:OPA330xxDBV", lay, "OPA365AIDBVR",
       {"3": mux, "4": buf, "1": buf, "5": avdd, "2": "GND"}, mpn="OPA365AIDBVR", desc="Unity-gain ADC driver: 50 MHz, zero-crossover rail-to-rail input")
    # charge-kickback RC as in the ADS7056 datasheet's 2.5 MSPS design (9.2.1): 33R + 680p C0G, corner 7.1 MHz;
    # the driver needs UGB >= 4 / (2 pi R C) = 28 MHz (OPA365: 50 MHz), and C >= 20 x 16 pF sampling cap
    res(sh, f"R_kick{ch}", "33R", buf, ainp, lay, "Charge-kick RC with 680p C0G, at the ADC pin")
    cap(sh, f"C_kick{ch}", "680p", ainp, "GND", lay)
    # AVDD is the ADC's reference: the datasheet asks for 3.3 uF low-ESR ceramic at the pin (no via between);
    # 4.7 uF 0603 X5R keeps about 3.3 uF at 3.3 V bias
    cap(sh, f"C_avdd{ch}", "100n", avdd, "GND", lay)
    cap(sh, f"C_avdd{ch}b", "4u7", avdd, "GND", lay, "AVDD = reference: >= 3.3 uF at the pin")
    lay.newline()
    ic(sh, f"U_adc{ch}", "control_card:ADS7056", lay, "ADS7056IRUGR",
       {"6": avdd, "7": ainp, "8": "GND", "5": "GND", "4": "+3V3", "1": f"ADC{ch}_CS_N_R",
        "3": f"ADC{ch}_SCLK_R", "2": f"ADC{ch}_SDO_R"}, mpn="ADS7056IRUGR", desc=f"ADC {ch}")
    cap(sh, f"C_dvdd{ch}", "1u", "+3V3", "GND", lay)
    for s in ("CS_N", "SCLK", "SDO"):
        # 33R as in the datasheet's 2.5 MSPS design: at 60 MHz SCLK, 100R into ~15-20 pF cost 1.5 ns of SDO timing
        res(sh, f"R_{s}{ch}", "33R", f"ADC{ch}_{s}_R", f"ADC{ch}_{s}", lay, "Series 33R (edge rate, 60 MHz SCLK)")
    lay.newline()


def mux_inputs(prefix):
    """X0..X7 nets for one mux: reference/mux_assignment.csv (tools/assign_mux.py, chosen to avoid
    crossing routes) if present, else U25's mapping. Channel numbers are remapped in the FPGA."""
    path = os.path.join(REF, "mux_assignment.csv")
    if os.path.exists(path):
        rows = [r for r in csv.DictReader(open(path)) if r["net"].startswith(prefix) or
                (r["net"] == "GND" and any(q["mux"] == r["mux"] and q["net"].startswith(prefix)
                                           for q in csv.DictReader(open(path))))]
        if len(rows) == 8:
            by_x = {int(r["x_input"][1:]): r["net"] for r in rows}
            return [by_x[i] for i in range(8)]
    return [f"{prefix}2", f"{prefix}1", f"{prefix}0", f"{prefix}3", f"{prefix}4", "GND", f"{prefix}5", f"{prefix}6"]


def sheet_adc():
    sh = sg.Sheet("ADC", "sheets/adc.kicad_sch", "A3", "Two 8:1 mux -> buffer -> ADS7056 chains (0..3.3 V)")
    D.sheets.append(sh)
    lay = Layout()
    maps = {ch: mux_inputs(p) for ch, p in (("A", "ADA"), ("B", "ADB"))}
    sh.text("Mux inputs are assigned to avoid crossing routes from J1 (reference/mux_assignment.csv); the FPGA "
            "renumbers the channels.\n" + "\n".join(f"Mux {ch}: " + " ".join(f"X{i}={n}" for i, n in enumerate(m))
                                                    for ch, m in maps.items()), 25.4, 12.7)
    for ch in ("A", "B"):
        adc_chain(sh, lay, ch, maps[ch])


def sheet_connector():
    sh = sg.Sheet("Header and LEDs", "sheets/connector.kicad_sch", "A3", "J1 to the power board, RGB LEDs")
    D.sheets.append(sh)
    lay = Layout()
    nets = {r["card_pin"]: header_net(r) for r in header_rows()}
    D.group = "header"
    ic(sh, "J_main", "Connector_Generic:Conn_02x25_Odd_Even", lay, "Power board",
       nets, fp="control_card:PinHeader_2x25_P1.27mm_Horizontal_U25", prefix="J",
       desc="Right-angle 2x25 1.27 mm to tube_power_5_1 J2 (mirrored numbering, see power_board_header.csv)")
    sh.text("Power board signals (all 3.3 V). Unused header pins are J1_Pnn spares on HVIO.", lay.x, lay.y)
    lay.newline()
    D.group = "leds"
    for k in (1, 2):   # two side-view LEDs on the north edge (three no longer fit beside the HyperRAM)
        ic(sh, f"D_rgb{k}", "control_card:LED_RGB_CA", lay, "RGB", {"2": "+3V3", "1": f"LED{k}_RK",
           "3": f"LED{k}_GK", "4": f"LED{k}_BK"}, mpn="APFA3010LSEEZGKQBKC", prefix="D",
           desc="Common-anode RGB LED, anode to 3.3 V, cathodes through 100R to the FPGA (active low)")
        for c in "RGB":
            res(sh, f"R_led{k}{c}", "100R", f"LED{k}_{c}K", f"LED{k}_{c}", lay)
        lay.newline()


# ------------------------------------------------------------------ main

def main():
    global D
    if not STOCK:
        raise SystemExit("set KICAD_SYMBOL_DIR to KiCad's share/kicad/symbols")
    cache = os.path.join(REF, "jlc_parts.csv")
    if os.path.exists(cache):
        for r in csv.DictReader(open(cache)):
            if r["lcsc"]:
                LCSC[r["mpn"]] = r["lcsc"]
    D = sg.Design(STOCK, HW)
    D.refs.update({"FPGA": "U1", "J_main": "J1", "J_jtag": "J2"})   # match the board and U25
    # parts added after the board was laid out take numbers after the existing ones, so earlier references stay put
    D.refs.update({f"C_{k}_{s}": f"C{65 + i}" for i, (k, s) in enumerate(
        (k, s) for k in ("plldig", "pll", "adc", "rcore") for s in ("b", "h"))})
    D.refs.update({"C_6c": "C73", "C_1v8hr_in": "C74", "C_1v8hr_out": "C75", "U_1v8hr": "U16", "C_6d": "C76"})
    for lib_id in ("Device:R", "Device:C", "Device:L", "Device:FerriteBead", "Device:NetTie_2", "power:PWR_FLAG",
                   "Regulator_Switching:AP61202Z6", "Regulator_Linear:TLV75512PDBV", "Regulator_Linear:TLV75533PDBV",
                   "Regulator_Linear:TLV75518PDBV",
                   "Memory_Flash:MT25QUxxxxxx1xW7", "Oscillator:ASE-xxxMHz", "74xx:74HC4051",
                   "Amplifier_Operational:OPA330xxDBV", "Connector_Generic:Conn_01x05",
                   "Connector_Generic:Conn_02x25_Odd_Even"):
        D.stock_symbol(lib_id)
    D.file_symbol(FPGA, os.path.join(HW, "lib", "agilex3.kicad_sym"), "A3CY025B-B18A")
    custom_symbols()
    assign = assign_pins()
    sheet_power()
    sheet_fpga_power(assign)
    sheet_config(assign)
    sheet_fpga_io(assign)
    sheet_memory()
    sheet_adc()
    sheet_connector()
    D.write()
    with open(os.path.join(REF, "bom_draft.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ref", "value", "footprint", "lcsc", "mpn", "dnp"])
        w.writerows(sorted(D.bom, key=lambda r: (re.sub(r"\d", "", r[0]), int(re.sub(r"\D", "", r[0]) or 0))))
    cli = os.environ.get("KICAD_CLI")
    if cli:
        for sh in D.sheets:
            subprocess.run([cli, "sch", "upgrade", "--force", os.path.join(HW, sh.file)], check=True,
                           capture_output=True)
        subprocess.run([cli, "sch", "upgrade", "--force", os.path.join(HW, "control_card.kicad_sch")], check=True,
                       capture_output=True)
        subprocess.run([cli, "sym", "upgrade", "--force", os.path.join(HW, "lib", "control_card.kicad_sym")],
                       check=True, capture_output=True)
    print(f"wrote {len(D.sheets)} sheets, {len(D.bom)} BOM lines")


if __name__ == "__main__":
    main()
