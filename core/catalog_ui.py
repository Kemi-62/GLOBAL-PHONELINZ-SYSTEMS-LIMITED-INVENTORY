# CATALOG_ROLES_V1
"""Shared helper: turn a flat list of stock items into Category > Sub-category groups
for the grouped catalog (partials/catalog_cards.html)."""


def _status(q):
    q = int(q or 0)
    return "out" if q <= 0 else ("low" if q <= 2 else "instock")


def build_catalog(items, prefix="cg", value_label="Value"):
    """items: list of dicts with keys
         pid, name, color, price, qty, imei, cat_id, cat_name, sub_id, sub_name,
         lines (list of {"label","value"}), extra (extra words to search), value (optional)
    Returns dict: groups, counts, total_units, total_value, value_label, empty
    """
    cats = {}
    counts = {"all": 0, "instock": 0, "low": 0, "out": 0}
    total_units = 0
    total_value = 0
    for it in items:
        st = _status(it.get("qty"))
        it = dict(it)
        it["status"] = st
        it["search"] = " ".join(
            str(x) for x in (it.get("name") or "", it.get("color") or "", it.get("imei") or "", it.get("extra") or "")
        ).lower()
        counts["all"] += 1
        if st != "out":
            counts["instock"] += 1
        if st == "low":
            counts["low"] += 1
        if st == "out":
            counts["out"] += 1
        total_units += int(it.get("qty") or 0)
        if it.get("value") is not None:
            total_value += it["value"]
        ckey = (it.get("cat_name") or "Uncategorised", it.get("cat_id") or 0)
        skey = (it.get("sub_name") or "Other", it.get("sub_id") or 0)
        cats.setdefault(ckey, {}).setdefault(skey, []).append(it)

    groups = []
    for (cname, cid) in sorted(cats, key=lambda k: (k[0].lower(), k[1])):
        subs = []
        n_cat = 0
        for (sname, sid) in sorted(cats[(cname, cid)], key=lambda k: (k[0].lower(), k[1])):
            its = sorted(cats[(cname, cid)][(sname, sid)], key=lambda i: ((i.get("name") or "").lower(), (i.get("color") or "").lower()))
            subs.append({"id": sid, "name": sname, "count": len(its), "items": its})
            n_cat += len(its)
        groups.append({"anchor": "%s-cat-%s" % (prefix, cid), "name": cname, "count": n_cat, "subs": subs})
    return {
        "groups": groups, "counts": counts, "total_units": total_units,
        "total_value": total_value, "value_label": value_label, "empty": not items,
    }
