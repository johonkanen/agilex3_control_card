"""Small KiCad schematic writer used by tools/gen_schematic.py.

Drawing style (same as the flying_cap_kicad generators): every symbol pin gets a
short wire stub and a net label. A net used on more than one sheet gets a global
label, otherwise a local label. Unused pins get a no-connect flag. Files are written
in the KiCad 9 format and upgraded with `kicad-cli sch upgrade`.
"""
import math
import os
import re
import uuid

SCH_VERSION = "20250114"
PROJECT = "control_card"
NS = uuid.UUID("3c1f6a2e-58d4-4b7a-9e0f-1a2b3c4d5e6f")
STUB = 2.54


def uid(*parts):
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


def q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def rnd(v):
    return round(v + 0.0, 4)


# ------------------------------------------------------------------ s-expression helpers

def _block_at(text, start):
    """Return text[start:end] for the balanced s-expression starting at `start`."""
    depth, i, n, in_str = 0, start, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    raise ValueError("unbalanced s-expression")


def find_symbol(text, name):
    m = re.search(r'\(symbol %s[\s)]' % re.escape(q(name)), text)
    if not m:
        return None
    return _block_at(text, m.start())


def symbol_from_file(path, name):
    """Load a library symbol, flattening `extends` (child keeps the parent's drawing)."""
    text = open(path).read()
    blk = find_symbol(text, name)
    if blk is None:
        raise SystemExit(f"symbol {name} not found in {path}")
    m = re.search(r'\(extends "([^"]+)"\)', blk)
    if m:
        parent = m.group(1)
        ppath = os.path.join(os.path.dirname(path), parent + ".kicad_sym")
        if not os.path.exists(ppath):
            ppath = path
        pblk = symbol_from_file(ppath, parent)
        pblk = pblk.replace(f'(symbol "{parent}_', f'(symbol "{name}_')
        pblk = pblk.replace(f"(symbol {q(parent)}", f"(symbol {q(name)}", 1)
        # the child's fields replace the parent's (KiCad flattens the same way)
        for pm in re.finditer(r'\(property "([^"]+)"', blk):
            cprop = _block_at(blk, pm.start())
            om = re.search(r'\(property %s' % re.escape(q(pm.group(1))), pblk)
            if om:
                pblk = pblk[:om.start()] + cprop + pblk[om.start() + len(_block_at(pblk, om.start())):]
            else:
                i = pblk.index("(symbol", 1)
                pblk = pblk[:i] + cprop + "\n\t\t" + pblk[i:]
        return pblk
    return blk


class LibSymbol:
    def __init__(self, lib_id, block):
        self.lib_id = lib_id
        name = re.match(r'\s*\(symbol "([^"]+)"', block).group(1)
        self.name = lib_id.split(":", 1)[1]
        if name != self.name:
            block = block.replace(f'(symbol "{name}_', f'(symbol "{self.name}_')
            block = block.replace(f"(symbol {q(name)}", f"(symbol {q(self.name)}", 1)
        self.block = block.replace(f"(symbol {q(self.name)}", f"(symbol {q(lib_id)}", 1)
        self.pins = {}      # number -> dict(x, y, angle, name, unit, etype)
        for sub in re.finditer(r'\(symbol "%s_(\d+)_(\d+)"' % re.escape(self.name), block):
            sblk = _block_at(block, sub.start())
            unit = int(sub.group(1))
            for pm in re.finditer(r'\(pin (\w+) \w+\s*\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)', sblk):
                pblk = _block_at(sblk, pm.start())
                nm = re.search(r'\(name "([^"]*)"', pblk).group(1)
                num = re.search(r'\(number "([^"]*)"', pblk).group(1)
                self.pins[num] = dict(x=float(pm.group(2)), y=float(pm.group(3)), angle=float(pm.group(4)),
                                      name=nm, unit=unit, etype=pm.group(1))
        self.bodies = {}    # unit -> list of (x0, y0, x1, y1) rectangles
        for sub in re.finditer(r'\(symbol "%s_(\d+)_(\d+)"' % re.escape(self.name), block):
            sblk = _block_at(block, sub.start())
            for rm in re.finditer(r'\(rectangle\s*\(start ([-\d.]+) ([-\d.]+)\)\s*\(end ([-\d.]+) ([-\d.]+)\)', sblk):
                self.bodies.setdefault(int(sub.group(1)), []).append(tuple(float(v) for v in rm.groups()))
        props = dict(re.findall(r'\(property "([^"]+)" "([^"]*)"', block))
        self.footprint = props.get("Footprint", "")
        self.ref_prefix = props.get("Reference", "U")

    def unit_bbox(self, unit):
        """(xmin, ymin, xmax, ymax) of pins and body rectangles, library coordinates."""
        xs = [p["x"] for p in self.unit_pins(unit).values()]
        ys = [p["y"] for p in self.unit_pins(unit).values()]
        for x0, y0, x1, y1 in self.bodies.get(unit, []) + self.bodies.get(0, []):
            xs += [x0, x1]
            ys += [y0, y1]
        return min(xs), min(ys), max(xs), max(ys)

    def unit_pins(self, unit):
        return {n: p for n, p in self.pins.items() if p["unit"] in (0, unit)}

    def units(self):
        return sorted({p["unit"] for p in self.pins.values() if p["unit"]}) or [1]


# ------------------------------------------------------------------ sheet model

class Sheet:
    def __init__(self, name, file, paper="A3", title=""):
        self.name, self.file, self.paper, self.title = name, file, paper, title or name
        self.items = []          # rendered s-expressions except labels
        self.labels = []         # (net, x, y, angle)
        self.symbols_used = set()
        self.drawn = set()
        self.texts = []

    # -- primitives
    def wire(self, x1, y1, x2, y2):
        self.items.append(f"""\t(wire
\t\t(pts
\t\t\t(xy {x1} {y1}) (xy {x2} {y2})
\t\t)
\t\t(stroke
\t\t\t(width 0)
\t\t\t(type default)
\t\t)
\t\t(uuid {q(uid(self.file, 'w', x1, y1, x2, y2))})
\t)""")

    def no_connect(self, x, y):
        self.items.append(f"""\t(no_connect
\t\t(at {x} {y})
\t\t(uuid {q(uid(self.file, 'nc', x, y))})
\t)""")

    def text(self, s, x, y, size=1.27):
        self.items.append(f"""\t(text {q(s)}
\t\t(exclude_from_sim no)
\t\t(at {x} {y} 0)
\t\t(effects
\t\t\t(font
\t\t\t\t(size {size} {size})
\t\t\t)
\t\t\t(justify left top)
\t\t)
\t\t(uuid {q(uid(self.file, 'text', s[:40], x, y))})
\t)""")


class Design:
    def __init__(self, stock_dir, project_dir):
        self.stock = stock_dir
        self.prj = project_dir
        self.libs = {}
        self.sheets = []
        self.refs = {}           # key -> reference
        self.counters = {}
        self.bom = []            # (ref, value, footprint, lcsc, mpn)
        self.root_uuid = uid("root")
        self.group = ""          # written to each placed symbol's "Group" field (used by tools/place.py)

    # -- libraries
    def stock_symbol(self, lib_id):
        lib, name = lib_id.split(":")
        path = os.path.join(self.stock, f"{lib}.kicad_symdir", f"{name}.kicad_sym")
        self.libs[lib_id] = LibSymbol(lib_id, symbol_from_file(path, name))
        return self.libs[lib_id]

    def file_symbol(self, lib_id, path, name):
        self.libs[lib_id] = LibSymbol(lib_id, symbol_from_file(path, name))
        return self.libs[lib_id]

    # -- references
    def ref_for(self, key, prefix):
        if key not in self.refs:
            taken = set(self.refs.values())
            while True:
                self.counters[prefix] = self.counters.get(prefix, 0) + 1
                ref = f"{prefix}{self.counters[prefix]}"
                if ref not in taken:
                    break
            self.refs[key] = ref
        return self.refs[key]

    def sheet_path(self, sheet):
        return f"/{self.root_uuid}/{uid('sheet', sheet.file)}"

    # -- placement
    def place(self, sh, key, lib_id, X, Y, value, nets, rot=0, unit=1, fp=None, lcsc="", mpn="",
              ds="", desc="", dnp=False, ref_key=None, prefix=None, in_bom=True):
        """nets: {pin number: net | None (no-connect) | '' (leave open, caller wires)}.
        Every pin of the unit must be listed."""
        sym = self.libs[lib_id]
        pins = sym.unit_pins(unit)
        missing = set(pins) - set(nets)
        extra = set(nets) - set(pins)
        if missing or extra:
            raise SystemExit(f"{key}: missing pins {sorted(missing)} unknown pins {sorted(extra)}")
        ref = self.ref_for(ref_key or key, prefix or sym.ref_prefix.rstrip("?") or "U")
        fp = sym.footprint if fp is None else fp
        sh.symbols_used.add(lib_id)
        two_pin = len(sym.pins) <= 2
        if two_pin:
            vert = rot % 180 == 0
            rx, ry, vx, vy = ((X + 2.54, Y - 1.27, X + 2.54, Y + 1.27) if vert
                              else (X - 2.54, Y - 3.81, X - 2.54, Y + 3.81))
        else:
            ys = [p["y"] for p in pins.values()] or [0]
            xs = [p["x"] for p in pins.values()] or [0]
            rx, ry = X + min(xs), Y - max(ys) - 3.81
            vx, vy = X + min(xs), Y - min(ys) + 3.81
        rx, ry, vx, vy = map(rnd, (rx, ry, vx, vy))

        def prop(name, val, x, y, hide=True):
            h = "\n\t\t\t(hide yes)" if hide else ""
            return f"""\t\t(property {q(name)} {q(val)}
\t\t\t(at {x} {y} 0){h}
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify left)
\t\t\t)
\t\t)"""
        props = [prop("Reference", ref, rx, ry, False), prop("Value", value, vx, vy, False),
                 prop("Footprint", fp, X, Y), prop("Datasheet", ds, X, Y), prop("Description", desc, X, Y),
                 prop("LCSC", lcsc, X, Y), prop("MPN", mpn, X, Y), prop("Group", self.group, X, Y)]
        pin_s = "\n".join(f"\t\t(pin {q(n)}\n\t\t\t(uuid {q(uid(sh.file, key, 'pin', n))})\n\t\t)" for n in sorted(pins))
        sh.items.append(f"""\t(symbol
\t\t(lib_id {q(lib_id)})
\t\t(at {X} {Y} {rot})
\t\t(unit {unit})
\t\t(exclude_from_sim no)
\t\t(in_bom {"yes" if in_bom else "no"})
\t\t(on_board yes)
\t\t(dnp {"yes" if dnp else "no"})
\t\t(uuid {q(uid(sh.file, key))})
{chr(10).join(props)}
{pin_s}
\t\t(instances
\t\t\t(project {q(PROJECT)}
\t\t\t\t(path {q(self.sheet_path(sh))}
\t\t\t\t\t(reference {q(ref)})
\t\t\t\t\t(unit {unit})
\t\t\t\t)
\t\t\t)
\t\t)
\t)""")
        if in_bom and (unit == sym.units()[0] or len(sym.units()) == 1):
            self.bom.append((ref, value, fp, lcsc, mpn, dnp))
        for n, net in nets.items():
            p = pins[n]
            r = math.radians(rot)
            px = p["x"] * math.cos(r) - p["y"] * math.sin(r)
            py = p["x"] * math.sin(r) + p["y"] * math.cos(r)
            x, y = rnd(X + px), rnd(Y - py)
            if (x, y) in sh.drawn or net == "":
                continue
            sh.drawn.add((x, y))
            if net is None:
                sh.no_connect(x, y)
                continue
            out = (p["angle"] + 180 + rot) % 360
            dx = round(math.cos(math.radians(out)), 6) * STUB
            dy = -round(math.sin(math.radians(out)), 6) * STUB
            x2, y2 = rnd(x + dx), rnd(y + dy)
            sh.wire(x, y, x2, y2)
            sh.labels.append((net, x2, y2, int(out)))
        return ref

    # -- output
    def render_labels(self, sh, global_nets):
        out = []
        for net, x, y, ang in sh.labels:
            just = "left" if ang in (0, 90) else "right"
            if net in global_nets:
                out.append(f"""\t(global_label {q(net)}
\t\t(shape passive)
\t\t(at {x} {y} {ang})
\t\t(fields_autoplaced yes)
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.27 1.27)
\t\t\t)
\t\t\t(justify {just})
\t\t)
\t\t(uuid {q(uid(sh.file, 'gl', net, x, y))})
\t\t(property "Intersheetrefs" "${{INTERSHEET_REFS}}"
\t\t\t(at {x} {y} 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(hide yes)
\t\t\t)
\t\t)
\t)""")
            else:
                out.append(f"""\t(label {q(net)}
\t\t(at {x} {y} {ang})
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.27 1.27)
\t\t\t)
\t\t\t(justify {just} bottom)
\t\t)
\t\t(uuid {q(uid(sh.file, 'l', net, x, y))})
\t)""")
        return out

    def lib_symbols(self, used):
        return "\n".join("\n".join("\t" + ln for ln in self.libs[k].block.split("\n")) for k in sorted(used))

    def write(self):
        nets_by_sheet = {}
        for sh in self.sheets:
            for net, *_ in sh.labels:
                nets_by_sheet.setdefault(net, set()).add(sh.file)
        global_nets = {n for n, s in nets_by_sheet.items() if len(s) > 1}
        for i, sh in enumerate(self.sheets):
            body = sh.items + self.render_labels(sh, global_nets)
            txt = f"""(kicad_sch
\t(version {SCH_VERSION})
\t(generator "eeschema")
\t(generator_version "9.0")
\t(uuid {q(uid('sheetfile', sh.file))})
\t(paper {q(sh.paper)})
\t(title_block
\t\t(title {q(sh.title)})
\t\t(rev "0.1")
\t\t(comment 1 "Generated by tools/gen_schematic.py")
\t)
\t(lib_symbols
{self.lib_symbols(sh.symbols_used)}
\t)
{chr(10).join(body)}
\t(embedded_fonts no)
)
"""
            path = os.path.join(self.prj, sh.file)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w", newline="\n").write(txt)
        self.write_root()
        return global_nets

    def write_root(self):
        blocks = []
        x0, y0, w, h, gap = 25.4, 38.1, 60.96, 15.24, 10.16
        for i, sh in enumerate(self.sheets):
            col, row = i % 3, i // 3
            x, y = rnd(x0 + col * (w + 25.4)), rnd(y0 + row * (h + gap + 10.16))
            su = uid("sheet", sh.file)
            blocks.append(f"""\t(sheet
\t\t(at {x} {y})
\t\t(size {w} {h})
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(dnp no)
\t\t(fields_autoplaced yes)
\t\t(stroke
\t\t\t(width 0.1524)
\t\t\t(type solid)
\t\t)
\t\t(fill
\t\t\t(color 0 0 0 0.0000)
\t\t)
\t\t(uuid {q(su)})
\t\t(property "Sheetname" {q(sh.name)}
\t\t\t(at {x} {rnd(y - 0.7)} 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify left bottom)
\t\t\t)
\t\t)
\t\t(property "Sheetfile" {q(sh.file)}
\t\t\t(at {x} {rnd(y + h + 0.6)} 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify left top)
\t\t\t)
\t\t)
\t\t(instances
\t\t\t(project {q(PROJECT)}
\t\t\t\t(path {q('/' + self.root_uuid)}
\t\t\t\t\t(page {q(str(i + 2))})
\t\t\t\t)
\t\t\t)
\t\t)
\t)""")
        txt = f"""(kicad_sch
\t(version {SCH_VERSION})
\t(generator "eeschema")
\t(generator_version "9.0")
\t(uuid {q(self.root_uuid)})
\t(paper "A4")
\t(title_block
\t\t(title "Agilex 3 control card (U25 replacement)")
\t\t(rev "0.1")
\t\t(comment 1 "Generated by tools/gen_schematic.py")
\t)
\t(lib_symbols
\t)
{chr(10).join(blocks)}
\t(sheet_instances
\t\t(path "/"
\t\t\t(page "1")
\t\t)
\t)
\t(embedded_fonts no)
)
"""
        open(os.path.join(self.prj, PROJECT + ".kicad_sch"), "w", newline="\n").write(txt)


# ------------------------------------------------------------------ custom box symbols

def box_symbol(name, left, right, ref="U", footprint="", desc="", datasheet="", top=(), bottom=()):
    """left/right/top/bottom: lists of (pin name, number, electrical type) or None for a gap."""
    rows = max(len(left), len(right), 1)
    cols = max(len(top), len(bottom), 0)
    h = rows * 2.54 + 2.54
    w = max(15.24, max([len(p[0]) for p in left + right if p] + [4]) * 1.27 * 2 + 5.08, cols * 2.54 + 5.08)
    w = math.ceil(w / 2.54) * 2.54
    top_y = math.floor(h / 2 / 2.54) * 2.54
    x0, x1 = -w / 2, w / 2
    y0, y1 = top_y, top_y - h
    pins = []

    def pin(p, x, y, ang):
        nm, num, et = p
        pins.append(f"""\t\t\t(pin {et} line
\t\t\t\t(at {rnd(x)} {rnd(y)} {ang})
\t\t\t\t(length 2.54)
\t\t\t\t(name {q(nm)}
\t\t\t\t\t(effects
\t\t\t\t\t\t(font
\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t\t(number {q(num)}
\t\t\t\t\t(effects
\t\t\t\t\t\t(font
\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)""")
    for i, p in enumerate(left):
        if p:
            pin(p, x0 - 2.54, y0 - 2.54 * (i + 1), 0)
    for i, p in enumerate(right):
        if p:
            pin(p, x1 + 2.54, y0 - 2.54 * (i + 1), 180)
    for i, p in enumerate(top):
        if p:
            pin(p, -(len(top) - 1) * 1.27 + 2.54 * i, y0 + 2.54, 270)
    for i, p in enumerate(bottom):
        if p:
            pin(p, -(len(bottom) - 1) * 1.27 + 2.54 * i, y1 - 2.54, 90)

    def prop(k, v, y, hide):
        hh = "\n\t\t\t(hide yes)" if hide else ""
        return f"""\t\t(property {q(k)} {q(v)}
\t\t\t(at 0 {rnd(y)} 0){hh}
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)"""
    return f"""\t(symbol {q(name)}
\t\t(pin_names
\t\t\t(offset 1.016)
\t\t)
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
{prop("Reference", ref, y0 + 3.81 + (2.54 if top else 0), False)}
{prop("Value", name, y1 - 3.81 - (2.54 if bottom else 0), False)}
{prop("Footprint", footprint, y1 - 6.35, True)}
{prop("Datasheet", datasheet, y1 - 8.89, True)}
{prop("Description", desc, y1 - 11.43, True)}
\t\t(symbol {q(name + "_0_1")}
\t\t\t(rectangle
\t\t\t\t(start {rnd(x0)} {rnd(y0)})
\t\t\t\t(end {rnd(x1)} {rnd(y1)})
\t\t\t\t(stroke
\t\t\t\t\t(width 0.254)
\t\t\t\t\t(type default)
\t\t\t\t)
\t\t\t\t(fill
\t\t\t\t\t(type background)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(symbol {q(name + "_1_1")}
{chr(10).join(pins)}
\t\t)
\t\t(embedded_fonts no)
\t)"""


def write_symbol_lib(path, blocks):
    txt = "(kicad_symbol_lib\n\t(version 20241209)\n\t(generator \"gen_schematic\")\n\t(generator_version \"9.0\")\n" \
          + "\n".join(blocks) + "\n)\n"
    open(path, "w", newline="\n").write(txt)
