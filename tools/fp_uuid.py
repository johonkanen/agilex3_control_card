"""Stable footprint UUIDs.

KiCad writes footprints in UUID order, and the placement and copper scripts take parts in board
order, so fresh random UUIDs on every rebuild would reshuffle parts that are interchangeable for
the scripts (identical caps, the two ADC chains). Footprints therefore keep the UUID recorded in
reference/footprint_uuids.csv (taken from the board the placement was approved on); a reference
not listed there gets a UUID derived from its name.
"""
import csv
import os
import uuid

import pcbnew

TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reference", "footprint_uuids.csv")
_known = None


def set_stable_uuid(fp, ref):
    global _known
    if _known is None:
        _known = {r["ref"]: r["uuid"] for r in csv.DictReader(open(TABLE))} if os.path.exists(TABLE) else {}
    u = _known.get(ref) or str(uuid.uuid5(uuid.NAMESPACE_URL, "control_card/footprint/" + ref))
    fp.SetUuidDirect(pcbnew.KIID(u))
