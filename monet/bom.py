"""The bill of materials of an assembly: what to print and how many, what to cut from stock, what to buy. Worked out
by the server from the build and the Note's BOM, a plain literal keyed by part name or pattern (as MATERIALS):

    BOM = {
        "vertebra_*": {"print": "vertebra"},                                  # a Note: its instances are counted
        "rail_*|post_*|mast": {"stock": "alu_tube_16x1.5", "material": "aluminium"},   # cut from stock: a cut list
        "projector": {"buy": "Epson EB-X49", "mass_g": 2700},                  # bought as it is
        "_extra": [{"buy": "M5x30 bolt + nut", "qty": 40}, {"buy": "M8 threaded rod", "length_mm": 300}],
    }

A stock part's cut length is how long it is along its own axis: the axis of its largest round face (a tube, a rod),
or else the direction it is longest in (a bar, a square tube). Nothing is counted by hand: more vertebrae in the
assembly are more in the list.
"""
import csv
import io

import numpy as np

from .materials import first

KINDS = ("print", "stock", "buy")


def problems_of(spec) -> list:
    """What is wrong with a BOM literal, in words."""
    if spec is None:
        return []
    if not isinstance(spec, dict):
        return ["BOM is {part or pattern: {print | stock | buy: …}, \"_extra\": [{buy, qty}, …]}"]
    out = []
    for key, entry in spec.items():
        if key == "_extra":
            if not isinstance(entry, list) or not all(isinstance(e, dict) and isinstance(e.get("buy") or e.get("stock"), str) for e in entry):
                out.append("BOM _extra is a list of {buy: name, qty} or {stock: name, length_mm, qty}")
            continue
        if not isinstance(entry, dict) or sum(k in entry for k in KINDS) != 1 or not isinstance(next((entry[k] for k in KINDS if k in entry), None), str):
            out.append(f"BOM[{key!r}] is one of {{print: Note}}, {{stock: name}}, {{buy: name}}")
    return out


def length_along(verts, tris, faces, part) -> tuple:
    """(length in mm, axis) of one part: along the axis of its largest cylindrical face, else its longest direction."""
    start, n = part["tris"]
    idx = np.unique(np.asarray(tris, dtype=np.int64).reshape(-1, 3)[start:start + n].reshape(-1))
    if not len(idx):
        return 0.0, None
    pts = np.asarray(verts, dtype=np.float64).reshape(-1, 3)[idx]
    f0, nf = part.get("faces") or [0, 0]
    cyl = [f for f in faces[f0:f0 + nf] if f.get("type") == "cylinder"]
    if cyl:
        axis = np.asarray(max(cyl, key=lambda f: f["area"])["axis"], dtype=float)
    else:
        centred = pts - pts.mean(0)
        axis = np.linalg.svd(centred, full_matrices=False)[2][0] if len(pts) > 2 else np.array([1.0, 0, 0])
    axis = axis / (np.linalg.norm(axis) or 1.0)
    along = pts @ axis
    return float(along.max() - along.min()), [round(float(x), 4) for x in axis]


def fits(size, bed) -> bool | None:
    if not bed or size is None:
        return None
    x, y, z = size
    return ((x <= bed[0] and y <= bed[1]) or (y <= bed[0] and x <= bed[1])) and (len(bed) < 3 or z <= bed[2])


def roll_up(spec: dict, parts: list, masses: dict, keepouts=(), length_of=None, printed_of=None, bed=None) -> dict:
    """The bill of materials. parts: the build's parts; masses: materials.of_parts(); length_of(part) -> (mm, axis);
    printed_of(note) -> {"size", "pieces": [sizes], "material"} of that Note's own build, or None."""
    spec = spec or {}
    out = {"printed": {}, "stock": {}, "bought": {}, "unlisted": [], "problems": problems_of(spec)}
    keep = set(keepouts or ())
    for q in parts:
        name = q["name"]
        if name in keep:
            continue
        key, entry = first(spec, name)
        if key is None or not isinstance(entry, dict):
            out["unlisted"].append(name)
            continue
        m = masses.get(name) or {}
        if "print" in entry:
            row = out["printed"].setdefault(entry["print"], {"qty": 0, "parts": [], "material": m.get("material"), "grams": 0.0})
            row["qty"] += 1
            row["parts"].append(name)
            row["grams"] += m.get("mass_g") or 0.0
        elif "stock" in entry:
            row = out["stock"].setdefault(entry["stock"], {"cuts": {}, "count": 0, "total_mm": 0.0, "material": entry.get("material") or m.get("material")})
            mm = round(length_of(q)[0], 1) if length_of else 0.0
            cut = row["cuts"].setdefault(mm, [])
            cut.append(name)
            row["count"] += 1
            row["total_mm"] += mm
        else:
            row = out["bought"].setdefault(entry["buy"], {"qty": 0, "parts": [], "mass_g": entry.get("mass_g")})
            row["qty"] += 1
            row["parts"].append(name)
    for e in spec.get("_extra") or [] if isinstance(spec.get("_extra"), list) else []:
        if not isinstance(e, dict):
            continue
        qty = int(e.get("qty", 1)) if isinstance(e.get("qty", 1), (int, float)) and not isinstance(e.get("qty"), bool) else 1
        if isinstance(e.get("stock"), str):
            row = out["stock"].setdefault(e["stock"], {"cuts": {}, "count": 0, "total_mm": 0.0, "material": e.get("material")})
            mm = round(float(e.get("length_mm") or 0), 1)
            row["cuts"].setdefault(mm, []).extend(["(extra)"] * qty)
            row["count"] += qty
            row["total_mm"] += mm * qty
        elif isinstance(e.get("buy"), str):
            row = out["bought"].setdefault(e["buy"], {"qty": 0, "parts": [], "mass_g": e.get("mass_g")})
            row["qty"] += qty
            if e.get("length_mm"):
                row["length_mm"] = e["length_mm"]
    for note, row in out["printed"].items():
        row["grams"] = round(row["grams"], 1)
        got = printed_of(note) if printed_of else None
        if got:
            sizes = got.get("pieces") or [got.get("size")]
            row["pieces"] = len(got["pieces"]) if got.get("pieces") else 1
            row["fits_bed"] = all(fits(s, bed) for s in sizes) if bed else None
            if got.get("material"):
                row["material"] = got["material"]
        else:
            row["fits_bed"] = None
            row["why"] = f"{note} has no build for its source as it is: build it to know whether it fits the bed"
    for row in out["stock"].values():
        row["cuts"] = [{"length_mm": mm, "qty": len(names), "parts": [n for n in names if n != "(extra)"]}
                       for mm, names in sorted(row["cuts"].items(), key=lambda kv: -kv[0])]
        row["total_mm"] = round(row["total_mm"], 1)
    out["counts"] = {"printed": sum(r["qty"] for r in out["printed"].values()), "stock": sum(r["count"] for r in out["stock"].values()),
                     "bought": sum(r["qty"] for r in out["bought"].values()), "unlisted": len(out["unlisted"])}
    return out


def as_csv(bom: dict) -> str:
    """The bill of materials as a spreadsheet: one line per thing to print, cut or buy."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["kind", "item", "qty", "length_mm", "material", "grams", "fits_bed", "parts"])
    for note, r in bom["printed"].items():
        w.writerow(["print", note, r["qty"], "", r.get("material") or "", r["grams"], {True: "yes", False: "no"}.get(r.get("fits_bed"), ""),
                    " ".join(r["parts"])])
    for stock, r in bom["stock"].items():
        for cut in r["cuts"]:
            w.writerow(["cut", stock, cut["qty"], cut["length_mm"], r.get("material") or "", "", "", " ".join(cut["parts"])])
        w.writerow(["stock", stock, r["count"], r["total_mm"], r.get("material") or "", "", "", "total"])
    for name, r in bom["bought"].items():
        w.writerow(["buy", name, r["qty"], r.get("length_mm", ""), "", r.get("mass_g") or "", "", " ".join(r["parts"])])
    for name in bom["unlisted"]:
        w.writerow(["unlisted", name, 1, "", "", "", "", name])
    return buf.getvalue()

