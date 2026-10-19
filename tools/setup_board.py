"""Board setup that tools/make_board.py does not cover: stackup, layer roles, via-in-pad
filling, and net classes.

    python3 -I tools/setup_board.py hardware/control_card.kicad_pcb

Stackup: JLC 6-layer "2313" build (from JLC's stackup table, assumed to be the 1.6 mm one;
check with JLC's impedance calculator). L1 (0.1) L2 (0.565 core) L3 (0.127) L4 (0.565 core)
L5 (0.1) L6, outer copper 1 oz, inner 0.5 oz. Dielectric constants are approximate.

Layer roles (KiCad In1..In4 = L2..L5): L2/L5 GND planes, L3 signal + 1.8/1.2 V pours,
L4 0.75 V island + 3.3 V fill. Vias are filled and capped (JLC 6-layer via-in-pad).
"""
import json
import os
import re
import sys

STACKUP = [
    # (layer, type, thickness mm, extra)
    ("F.SilkS", "Top Silk Screen", None, ""),
    ("F.Paste", "Top Solder Paste", None, ""),
    ("F.Mask", "Top Solder Mask", 0.01, ""),
    ("F.Cu", "copper", 0.035, ""),
    ("dielectric 1", "prepreg", 0.1, '(material "2313 FR4") (epsilon_r 4.05) (loss_tangent 0.02)'),
    ("In1.Cu", "copper", 0.0152, ""),
    ("dielectric 2", "core", 0.565, '(material "FR4") (epsilon_r 4.6) (loss_tangent 0.02)'),
    ("In2.Cu", "copper", 0.0152, ""),
    ("dielectric 3", "prepreg", 0.127, '(material "2116 FR4") (epsilon_r 4.16) (loss_tangent 0.02)'),
    ("In3.Cu", "copper", 0.0152, ""),
    ("dielectric 4", "core", 0.565, '(material "FR4") (epsilon_r 4.6) (loss_tangent 0.02)'),
    ("In4.Cu", "copper", 0.0152, ""),
    ("dielectric 5", "prepreg", 0.1, '(material "2313 FR4") (epsilon_r 4.05) (loss_tangent 0.02)'),
    ("B.Cu", "copper", 0.035, ""),
    ("B.Mask", "Bottom Solder Mask", 0.01, ""),
    ("B.Paste", "Bottom Solder Paste", None, ""),
    ("B.SilkS", "Bottom Silk Screen", None, ""),
]
LAYER_ROLES = {"In1.Cu": ("power", "L2.GND"), "In2.Cu": ("signal", "L3.SIG_1V8_1V2"),
               "In3.Cu": ("power", "L4.0V75_3V3"), "In4.Cu": ("power", "L5.GND")}

# name: (track, clearance, via diameter, via drill, nets / patterns)
NETCLASSES = {
    "PWR_CORE": (0.5, 0.1, 0.45, 0.25, ["+0V75"]),
    "PWR": (0.3, 0.1, 0.45, 0.25, ["+5V", "+3V3", "+1V8", "+1V2", "+3V3A"]),
    "GND": (0.3, 0.1, 0.45, 0.25, ["GND"]),
    "SW": (0.5, 0.15, 0.45, 0.25, ["/Power/SW_*"]),
    "SENSE": (0.15, 0.1, 0.35, 0.2, ["VCC_SENSE_P", "VCC_SENSE_N"]),
}
# name: (diff pair width, gap, via gap); the _P/_N net suffix makes KiCad's router treat the nets as a pair
DIFF_PAIRS = {"SENSE": (0.15, 0.15, 0.25)}

# Pre-defined sizes for the PCB editor's Track/Via dropdowns (W / Shift+W cycles widths while routing).
# KiCad keeps a 0 placeholder first, the "use netclass" entry.
TRACK_PRESETS = [0.1, 0.15, 0.2, 0.3, 0.5]
VIA_PRESETS = [(0.3, 0.15), (0.35, 0.2), (0.45, 0.25)]

# Custom design rules (.kicad_dru). The core sense pair only carries DC feedback, so its pair rules are
# deliberately loose: any gap from minimum clearance up to 5 mm, and uncoupled length and skew barely limited.
DRU = """(version 1)

(rule "sense_pair_loose"
	(condition "A.hasNetclass('SENSE')")
	(constraint diff_pair_gap (min 0.1mm) (opt 0.15mm) (max 5mm))
	(constraint diff_pair_uncoupled (max 100mm))
	(constraint skew (max 50mm)))

# JLCPCB multilayer limits that KiCad's global minimums do not express (jlcpcb.com/capabilities, 2026-10-17):
# plated through-hole (connector pin) hole to other-net tracks 0.28 mm, and their hole-to-hole 0.45 mm. A via next to a
# pin is held by JLC's via rules instead (via hole to copper 0.2 mm); the routers still keep via copper 0.28 mm from pin holes
(rule "jlc_pth_hole_to_copper"
	(condition "A.Type == 'Pad' && A.Pad_Type == 'Through-hole' && A.Net != B.Net && B.Type != 'Via'")
	(constraint hole_clearance (min 0.28mm)))

(rule "jlc_pth_to_via"
	(condition "A.Type == 'Pad' && A.Pad_Type == 'Through-hole' && A.Net != B.Net && B.Type == 'Via'")
	(constraint hole_clearance (min 0.2mm)))

(rule "jlc_pth_hole_to_hole"
	(condition "A.Type == 'Pad' && A.Pad_Type == 'Through-hole' && B.Type == 'Pad' && B.Pad_Type == 'Through-hole'")
	(constraint hole_to_hole (min 0.45mm)))
"""


def stackup_sexpr():
    out = ["\t\t(stackup"]
    for name, typ, th, extra in STACKUP:
        t = f" (thickness {th})" if th is not None else ""
        e = f" {extra}" if extra else ""
        out.append(f'\t\t\t(layer "{name}" (type "{typ}"){t}{e})')
    out += ['\t\t\t(copper_finish "ENIG")', "\t\t\t(dielectric_constraints no)", "\t\t)"]
    return "\n".join(out)


def setup_pcb(path):
    t = open(path).read()
    t = re.sub(r"\n\t\t\(stackup\n.*?\n\t\t\)(?=\n)", "", t, flags=re.S)
    t = t.replace("\t(setup\n", "\t(setup\n" + stackup_sexpr() + "\n", 1)
    for flag in ("capping", "filling"):
        t = re.sub(r"\(%s no\)" % flag, f"({flag} yes)", t, count=1)
    for layer, (typ, user) in LAYER_ROLES.items():
        t = re.sub(r'\((\d+) "%s" \w+( "[^"]*")?\)' % re.escape(layer), rf'(\1 "{layer}" {typ} "{user}")', t, count=1)
    open(path, "w", newline="\n").write(t)


def setup_netclasses(pro):
    d = json.load(open(pro))
    ns = d["net_settings"]
    default = next(c for c in ns["classes"] if c["name"] == "Default")
    ns["classes"] = [default]
    patterns = []
    for i, (name, (track, clr, vd, vdr, nets)) in enumerate(NETCLASSES.items()):
        c = dict(default)
        c.update(name=name, track_width=track, clearance=clr, via_diameter=vd, via_drill=vdr, priority=i)
        if name in DIFF_PAIRS:
            c.update(zip(("diff_pair_width", "diff_pair_gap", "diff_pair_via_gap"), DIFF_PAIRS[name]))
        ns["classes"].append(c)
        patterns += [{"netclass": name, "pattern": n} for n in nets]
    ns["netclass_patterns"] = patterns
    ds = d["board"]["design_settings"]
    ds["track_widths"] = [0.0] + TRACK_PRESETS
    ds["via_dimensions"] = [{"diameter": 0.0, "drill": 0.0}] + [{"diameter": a, "drill": b} for a, b in VIA_PRESETS]
    json.dump(d, open(pro, "w"), indent=2)


def main(pcb):
    setup_pcb(pcb)
    setup_netclasses(os.path.splitext(pcb)[0] + ".kicad_pro")
    open(os.path.splitext(pcb)[0] + ".kicad_dru", "w", newline="\n").write(DRU)
    print("stackup, layer roles, via filling, net classes and custom rules set")


if __name__ == "__main__":
    main(sys.argv[1])
