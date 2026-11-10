"""What a part is made of and what it weighs: worked out by the server when it reports, from the build and the Note's
literals. Nothing here needs a build again: a material is no shape.

    MATERIAL = "petg"                                          # a Note: what it is printed in (else the project's)
    MATERIALS = {"mast|rail_*": "aluminium", "projector": None}  # an assembly: by part name or pattern; None: bought
    MASS = {"projector": 2700}                                 # grams, for what is bought or not drawn as it is

A pattern is a part's name with * and ? for any letters, and | between alternatives ("rail_*|post_*"). The first key
that matches a part decides. The profiles are profiles/materials/<name>.json: density (g/cm³), max_temp_c (where it
starts to soften or creep), printed (whether the printer's checks apply to it).
"""
import fnmatch
import math

G = 9.80665     # m/s²


def matches(pattern: str, name: str) -> bool:
    """Does a part's name match a key of MATERIALS, MASS or BOM: * and ? within each alternative, | between them."""
    return any(fnmatch.fnmatchcase(name, alt.strip()) for alt in str(pattern).split("|") if alt.strip())


def first(table, name: str):
    """(key, value) of the first entry of a table whose key matches the name, or (None, None)."""
    for key, value in (table or {}).items() if isinstance(table, dict) else ():
        if not str(key).startswith("_") and matches(key, name):
            return key, value
    return None, None


def keepouts(part_names, spec) -> list:
    """The parts that are room to keep clear, not material: named keepout_<…>, or listed in the Note's KEEPOUT
    (a list of names, or {name: {"on": part}})."""
    listed = set(spec or ()) if isinstance(spec, (list, tuple, dict)) else set()
    return [n for n in part_names if n.split("/")[-1].startswith("keepout_") or n in listed]


def problems_of(parsed: dict, known: set) -> list:
    """What is wrong with a Note's MATERIAL, MATERIALS and MASS, in words."""
    out = []
    m = parsed.get("material")
    if m is not None and (not isinstance(m, str) or m not in known):
        out.append(f"MATERIAL {m!r}: one of {', '.join(sorted(known))}")
    mats = parsed.get("materials")
    if mats is not None:
        if not isinstance(mats, dict):
            out.append("MATERIALS is {part or pattern: material, or None for a bought part}")
        else:
            out += [f"MATERIALS[{k!r}] = {v!r}: one of {', '.join(sorted(known))}, or None for a bought part"
                    for k, v in mats.items() if v is not None and v not in known]
    mass = parsed.get("mass")
    if mass is not None:
        if not isinstance(mass, dict):
            out.append("MASS is {part or pattern: grams}")
        else:
            out += [f"MASS[{k!r}] = {v!r}: grams, a number above 0" for k, v in mass.items()
                    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0]
    return out


def of_parts(parsed: dict, parts: list, default: str | None, profiles: dict, note_material=None, bom_of=None) -> dict:
    """{part name: {"material", "mass_g", "volume_cm3", "printed", "how"}} for the parts of a build (a plain Note is
    one part). The material: MATERIALS by name, else what the BOM says the part is (a printed Note's own MATERIAL,
    stock's `material`), else the Note's MATERIAL, else the project's. The mass: MASS by name, else the BOM's
    `mass_g`, else volume x density. A bought part (None) with no mass given has none: `mass_g` None.
    note_material(note) -> the MATERIAL of another Note of the project; bom_of(part) -> its BOM entry or None."""
    own = parsed.get("material") if isinstance(parsed.get("material"), str) else None
    out = {}
    for q in parts:
        name, vol = q["name"], float(q.get("volume") or 0.0)
        how = "project"
        key, mat = first(parsed.get("materials"), name)
        entry = bom_of(name) if bom_of else None
        if key is not None:
            how = f"MATERIALS[{key!r}]"
        elif isinstance(entry, dict) and "buy" in entry:
            mat, how = None, "BOM: bought"
        elif isinstance(entry, dict) and entry.get("material"):
            mat, how = entry["material"], "BOM"
        elif isinstance(entry, dict) and entry.get("print") and note_material and note_material(entry["print"]):
            mat, how = note_material(entry["print"]), f"MATERIAL of {entry['print']}"
        elif own:
            mat, how = own, "MATERIAL"
        else:
            mat = default
        profile = profiles.get(mat) if mat else None
        row = {"material": mat, "volume_cm3": round(vol / 1000, 4), "printed": bool(profile and profile.get("printed")), "how": how,
               "mass_g": None}
        mkey, grams = first(parsed.get("mass"), name)
        if mkey is not None and isinstance(grams, (int, float)) and not isinstance(grams, bool):
            row.update(mass_g=round(float(grams), 3), mass_from=f"MASS[{mkey!r}]")
        elif isinstance(entry, dict) and isinstance(entry.get("mass_g"), (int, float)) and not isinstance(entry.get("mass_g"), bool):
            row.update(mass_g=round(float(entry["mass_g"]), 3), mass_from="BOM")
        elif profile and isinstance(profile.get("density"), (int, float)):
            row.update(mass_g=round(vol / 1000 * float(profile["density"]), 3), mass_from="volume x density")
        out[name] = row
    return out


def summary(rows: dict) -> dict:
    """The whole: total grams of what has a mass, and what has none."""
    known = [r["mass_g"] for r in rows.values() if r["mass_g"] is not None]
    return {"mass_g": round(sum(known), 3), "unknown": sorted(n for n, r in rows.items() if r["mass_g"] is None),
            "by_material": {m: round(sum(r["mass_g"] or 0 for r in rows.values() if r["material"] == m), 3)
                            for m in sorted({r["material"] or "bought" for r in rows.values()} - {"bought"})}}


def centres(verts, tris, parts) -> dict:
    """{part: centre of its volume [x, y, z]} from the preview mesh (closed, outward): the divergence theorem, a
    signed tetrahedron to the origin per triangle. None where the mesh has no volume."""
    import numpy as np
    V = np.asarray(verts, dtype=np.float64).reshape(-1, 3)
    T = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    out = {}
    for q in parts:
        start, n = q["tris"]
        t = T[start:start + n]
        if not len(t):
            out[q["name"]] = None
            continue
        a, b, c = V[t[:, 0]], V[t[:, 1]], V[t[:, 2]]
        vol = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
        total = vol.sum()
        out[q["name"]] = None if abs(total) < 1e-9 else ((a + b + c) / 4.0 * vol[:, None]).sum(0) / total
    return out
