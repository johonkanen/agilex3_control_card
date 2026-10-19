#!/usr/bin/env python3
"""Look up parts in the JLCPCB assembly library (stock, basic/extended, C-number).

Usage: python3 tools/jlc_search.py <keyword> [<keyword> ...] [-n 8]
Prints one line per hit: C-number, library type, stock, package, MPN, description.
"""
import json
import sys
import urllib.request

URL = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def search(keyword, n=8):
    body = json.dumps({"keyword": keyword, "currentPage": 1, "pageSize": n}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    info = (data.get("data") or {}).get("componentPageInfo") or {}
    return info.get("total", 0), info.get("list") or []


def main():
    args = sys.argv[1:]
    n = 8
    if "-n" in args:
        i = args.index("-n")
        n = int(args[i + 1])
        del args[i:i + 2]
    for kw in args:
        total, hits = search(kw, n)
        print(f"== {kw}: {total} hits")
        for h in hits:
            code = h.get("componentCode") or (h.get("urlSuffix") or "").split("/")[-1]
            lib = {"base": "BASIC", "expand": "ext"}.get(h.get("componentLibraryType"), h.get("componentLibraryType"))
            print(f"  {code:10} {lib:6} stock={h.get('stockCount'):>7}  {h.get('componentSpecificationEn') or h.get('encapsulationNumber') or '':14} "
                  f"{h.get('componentModelEn') or h.get('urlSuffix', '').split('/')[0]:28} {h.get('describe') or h.get('erpComponentName') or ''}"[:200])


if __name__ == "__main__":
    main()
