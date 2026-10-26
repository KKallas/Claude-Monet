"""
Putting Notes at snap points: for an assembly's build(), the instances its PLACED names. Not a Note.

PLACED = {"<instance>": {"note": "<a Note of this project>", "at": "<snap point>", "turn": 0 | 90 | 180 | 270}}
is written by the canvas (Assembly: Place) or by the agent; SNAPS says where the snap points are. Every instance is
the Note's own build(), turned about Z by `turn` and moved so the Note's 0 is at the snap point, labelled with the
instance's name. The server holds each one on the part its snap point is on (a block on the grid slides with it).
"""
import importlib

from build123d import Compound, Pos, Rot


def moved(shape, where):
    """The shape moved, an assembly part by part: moving a Compound whole leaves its children where they were."""
    kids = list(getattr(shape, "children", ()) or ())
    if kids:
        return Compound(children=[moved(k, where) for k in kids], label=shape.label)
    out = where * shape
    out.label = shape.label
    return out


def placed(PLACED, SNAPS):
    """The instances, ready to go into the assembly's children."""
    out = []
    for name, spec in (PLACED or {}).items():
        snap = SNAPS.get(spec["at"])
        if snap is None:
            raise KeyError(f"PLACED {name!r}: there is no snap point {spec['at']!r}")
        part = importlib.import_module(spec["note"]).build()
        one = moved(part, Pos(*snap["at"]) * Rot(0, 0, snap.get("turn", 0) + spec.get("turn", 0)))
        one.label = name
        out.append(one)
    return out
