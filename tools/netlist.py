"""Read a KiCad s-expression netlist: {net name: [(ref, pin), ...]}."""
import re


def load(path):
    t = open(path).read()
    nets = {}
    for blk in re.split(r"\n\t\t\(net\n", t[t.index("\t(nets"):])[1:]:
        name = re.search(r'\(name "([^"]*)"\)', blk).group(1)
        nets[name.lstrip("/")] = re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', blk)
    return nets
