#!/usr/bin/env python3
"""Look up every MPN in reference/bom_draft.csv at JLCPCB and cache the result.

    python3 -I tools/jlc_bom.py

Writes reference/jlc_parts.csv (mpn, lcsc, library type, stock, package). The
schematic generator reads it to fill the LCSC field. An MPN is matched exactly
(case-insensitive); among exact hits the one with most stock wins.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "jlc"))
import jlc_search  # noqa: E402

REF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reference")


def main():
    bom = list(csv.DictReader(open(os.path.join(REF, "bom_draft.csv"))))
    need = {}
    for r in bom:
        if r["mpn"] and not r["ref"].startswith(("#", "NT")):
            need.setdefault(r["mpn"], 0)
            need[r["mpn"]] += 1
    out = []
    for mpn, qty in sorted(need.items()):
        _, hits = jlc_search.search(mpn, 10)
        exact = [h for h in hits if (h.get("componentModelEn") or "").upper() == mpn.upper()]
        best = max(exact or hits[:1], key=lambda h: h.get("stockCount") or 0, default=None)
        if best is None:
            out.append(dict(mpn=mpn, qty=qty, lcsc="", lib="", stock=0, package="", match="none"))
            continue
        out.append(dict(mpn=mpn, qty=qty, lcsc=best.get("componentCode", ""),
                        lib={"base": "basic", "expand": "ext"}.get(best.get("componentLibraryType"), ""),
                        stock=best.get("stockCount") or 0, package=best.get("componentSpecificationEn") or "",
                        match="exact" if exact else "fuzzy: " + (best.get("componentModelEn") or "")))
    with open(os.path.join(REF, "jlc_parts.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["mpn", "qty", "lcsc", "lib", "stock", "package", "match"])
        w.writeheader()
        w.writerows(out)
    for r in out:
        flag = "" if r["match"] == "exact" and int(r["stock"]) >= 5 * r["qty"] else "  <-- check"
        print(f"{r['mpn']:32} x{r['qty']:<3} {r['lcsc']:10} {r['lib']:5} stock={r['stock']:<7} {r['match']}{flag}")


if __name__ == "__main__":
    main()
