"""Semmelweis: the load check. Wash your hands before touching the next patient.

Before a part is edited it is rebuilt from its Note and compared with what was saved:
fingerprint first, then every tag's measurements. Green: identical. Yellow: within
print tolerance (usually a library update). Red: something changed, and the agent may
not edit until the user has looked.
"""

SAME = 1e-6   # relative: below this two builds are the same build


def fingerprint(shape) -> dict:
    """Volume, surface area, bounding box and centre of mass of a build123d shape. Milliseconds."""
    from build123d import CenterOf
    bb = shape.bounding_box()
    com = shape.center(CenterOf.MASS)
    return {
        "volume": shape.volume,
        "area": shape.area,
        "bbox": [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z],
        "com": [com.X, com.Y, com.Z],
        "solids": len(shape.solids()),
        "faces": len(shape.faces()),
    }


def _numbers(measure: dict):
    for k, v in measure.items():
        if isinstance(v, bool):
            yield k, v
        elif isinstance(v, (int, float)):
            yield k, float(v)
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                if isinstance(x, (int, float)):
                    yield f"{k}[{i}]", float(x)


def compare(saved: dict, now: dict, tol: float = 0.1) -> dict:
    """saved / now: {"fingerprint": {...}, "tags": {name: {"resolved", "measure"}}}. tol: print tolerance, mm."""
    a, b = saved["fingerprint"], now["fingerprint"]
    size = max(1.0, *(abs(b["bbox"][i + 3] - b["bbox"][i]) for i in range(3)))
    notes, worst = [], "green"

    def judge(name, d, same, ok):
        nonlocal worst
        if abs(d) <= same:
            return
        level = "yellow" if abs(d) <= ok else "red"
        notes.append({"what": name, "delta": round(d, 6), "level": level})
        if level == "red" or worst == "green":
            worst = level

    # a surface moved by tol changes the volume by about area * tol
    judge("volume", b["volume"] - a["volume"], SAME * max(1.0, abs(a["volume"])), a["area"] * tol)
    judge("area", b["area"] - a["area"], SAME * max(1.0, abs(a["area"])), 0.02 * a["area"])
    for i, name in enumerate(("min_x", "min_y", "min_z", "max_x", "max_y", "max_z")):
        judge(name, b["bbox"][i] - a["bbox"][i], SAME * size, tol)
    for i, name in enumerate(("com_x", "com_y", "com_z")):
        judge(name, b["com"][i] - a["com"][i], SAME * size, tol)
    if a.get("solids") != b.get("solids"):
        notes.append({"what": "solids", "delta": b.get("solids", 0) - a.get("solids", 0), "level": "red"})
        worst = "red"

    for name, was in (saved.get("tags") or {}).items():
        is_ = (now.get("tags") or {}).get(name)
        if is_ is None or (was.get("resolved") and not is_.get("resolved")):
            notes.append({"what": f"tag {name}", "delta": None, "level": "red", "why": "no longer found" if is_ else "tag removed"})
            worst = "red"
            continue
        then = dict(_numbers(was.get("measure", {})))
        for k, v in _numbers(is_.get("measure", {})):
            if k not in then:
                continue
            if isinstance(v, bool) or isinstance(then[k], bool):
                if v != then[k]:
                    notes.append({"what": f"tag {name}.{k}", "delta": None, "level": "red", "why": f"was {then[k]}, is {v}"})
                    worst = "red"
            else:
                judge(f"tag {name}.{k}", v - then[k], SAME * size, tol)
    return {"status": worst, "tolerance": tol, "changes": notes}
