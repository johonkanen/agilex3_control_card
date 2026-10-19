"""Dump every sheet of an .xlsx to CSV using only the standard library.

    python3 -I tools/xlsx_to_csv.py A3CY025B.xlsx out_dir
"""
import csv
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def col_index(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def main(path, out_dir):
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels}
    os.makedirs(out_dir, exist_ok=True)
    for sh in wb.find("m:sheets", NS):
        name = sh.get("name")
        xml = ET.fromstring(z.read("xl/" + target[sh.get(f"{{{NS['r']}}}id")].lstrip("/").replace("xl/", "")))
        rows = []
        for row in xml.iter(f"{{{NS['m']}}}row"):
            vals = {}
            for c in row.findall("m:c", NS):
                v = c.find("m:v", NS)
                t = c.get("t")
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
                else:
                    val = v.text if v is not None else ""
                vals[col_index(c.get("r"))] = val
            if vals:
                rows.append([vals.get(i, "") for i in range(max(vals) + 1)])
        out = os.path.join(out_dir, re.sub(r"[^\w.-]+", "_", name) + ".csv")
        with open(out, "w", newline="") as f:
            csv.writer(f).writerows(rows)
        print(f"{name}: {len(rows)} rows -> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
