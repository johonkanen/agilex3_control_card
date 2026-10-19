"""Bring schematic changes into the PCB from a KiCad netlist, like Update PCB from Schematic.

    kicad-cli sch export netlist --format kicadsexpr -o /tmp/cc.net hardware/control_card.kicad_sch
    KICAD_FOOTPRINT_DIR=.../share/kicad/footprints squashfs-root/AppRun python3.11 -I \
        tools/sync_pcb.py /tmp/cc.net hardware/control_card.kicad_pcb

Footprints already on the board (matched by reference) keep their position. New
ones are parked in a column to the right of the board for tools/place.py. Each
footprint gets the symbol's KIID path, so KiCad's own Update PCB treats them as
linked. Pad nets are set from the netlist.
"""
import os
import re
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fp_uuid import set_stable_uuid  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_LIBS = {"control_card": os.path.join(HERE, "..", "hardware", "lib", "control_card.pretty")}


def blocks(text, head):
    """Yield the balanced s-expressions that start with `(head`."""
    for m in re.finditer(r"\(%s\b" % head, text):
        depth, i = 0, m.start()
        in_str = False
        while True:
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
                    yield text[m.start():i + 1]
                    break
            i += 1


def parse(path):
    t = open(path).read()
    comps = []
    for b in blocks(t[t.index("(components"):t.index("(libparts")], "comp"):
        g = lambda k: (re.search(r'\(%s "([^"]*)"\)' % k, b) or [None, ""])[1]   # noqa: E731
        sp = re.search(r'\(sheetpath\s*\(names "[^"]*"\)\s*\(tstamps "([^"]*)"\)\s*\)', b)
        sheet_ts = sp.group(1)
        ts = re.search(r'\(tstamps "([^"]+)"', b[sp.end():]).group(1)   # the symbol's own, after the sheetpath
        fields = dict(re.findall(r'\(field\s*\(name "([^"]+)"\)\s*"([^"]*)"\)', b))
        comps.append(dict(ref=g("ref"), value=g("value"), footprint=g("footprint"), path=sheet_ts + ts,
                          sheetname=re.search(r'\(names "([^"]*)"\)', b).group(1), fields=fields,
                          dnp='(name "dnp")' in b))
    nets = {}
    for b in blocks(t[t.index("(nets"):], "net"):
        name = re.search(r'\(name "([^"]*)"\)', b).group(1)
        nets[name] = re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', b)
    return comps, nets


def load_fp(lib_id):
    lib, name = lib_id.split(":")
    path = PROJECT_LIBS.get(lib) or os.path.join(os.environ["KICAD_FOOTPRINT_DIR"], lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise SystemExit(f"footprint {lib_id} not found in {path}")
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def main(net_path, pcb_path):
    comps, nets = parse(net_path)
    board = pcbnew.LoadBoard(pcb_path)
    have = {fp.GetReference(): fp for fp in board.GetFootprints()}
    park_x, park_y = pcbnew.FromMM(140), pcbnew.FromMM(90)
    added = 0
    for c in comps:
        if not c["footprint"] or c["ref"].startswith("#"):
            continue
        fp = have.get(c["ref"])
        if fp is None:
            fp = load_fp(c["footprint"])
            fp.SetReference(c["ref"])
            set_stable_uuid(fp, c["ref"])
            board.Add(fp)
            fp.SetPosition(pcbnew.VECTOR2I(park_x, park_y + pcbnew.FromMM(4) * added))
            added += 1
        lib, name = c["footprint"].split(":")
        if fp.GetFPID().GetLibItemName() == name:
            fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetDNP(c["dnp"])
        fp.SetValue(c["value"])
        for k in ("LCSC", "MPN", "Group", "Description", "Datasheet"):
            v = c["fields"].get(k, "")
            if k in ("Description", "Datasheet") and not v:
                continue
            fp.SetField(k, v)
            fld = fp.GetField(k)
            if fld is not None and k not in ("Reference", "Value"):
                fld.SetVisible(False)
                fld.SetLayer(pcbnew.F_Fab)
        fp.SetPath(pcbnew.KIID_PATH(c["path"]))
        fp.SetSheetname(c["sheetname"].strip("/"))
    refs = {fp.GetReference(): fp for fp in board.GetFootprints()}
    for fp in refs.values():
        for pad in fp.Pads():
            pad.SetNetCode(0)
    missing = []
    for name, nodes in nets.items():
        ni = board.FindNet(name)
        if ni is None:
            ni = pcbnew.NETINFO_ITEM(board, name)
            board.Add(ni)
        for ref, pin in nodes:
            fp = refs.get(ref)
            pads = [p for p in fp.Pads() if p.GetNumber() == pin] if fp else []
            if not pads:
                missing.append(f"{ref}.{pin}")
            for p in pads:
                p.SetNet(ni)
    board.Save(pcb_path)
    print(f"{len(comps)} components ({added} new), {len(nets)} nets")
    if missing:
        print("pads not found:", " ".join(missing[:40]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
