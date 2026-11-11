"""The lights in a Note (LIGHTS, a plain literal: a fact, not a shape): where each is, which part it rides, which way
it shines, how wide and how strong. Checked here against the build's parts, without running anything; the canvas
draws them (canvas/lights.js): the light where it lands, the beam in the air, a part that glows with it.

    LIGHTS = {
      "led":   {"kind": "spot", "on": "head", "at": [0, 0, -12], "aim": [0, 0, -1], "angle": 60, "lumens": 800},
      "proj":  {"kind": "projector", "on": "head", "at": [40, 0, -5], "aim": [0, 0.3, -1], "throw": 1.2, "aspect": "16:9"},
      "laser": {"kind": "laser", "on": "turret", "at": [0, 0, 20], "aim": [1, 0, 0], "fan": 40, "mw": 50},
      "strip": {"kind": "glow", "glow": "inner_layer", "lumens": 2000, "color": "#9fd8ff"},
    }

`at` and `aim` are as built (the Note's frame, joints at 0); a light moves with the part it is `on` as the joints
move. Strength in lumens (a laser's in mW); `angle` a spot's whole beam in degrees, `soft` how much of its edge
fades; a projector's beam from its throw ratio (distance / picture width), aspect and `offset` (where the picture's
middle is above the lens axis, in picture heights: 0.5 puts its lower edge on the axis); a laser is a line, or with
`fan` (degrees) a sheet spread `across`. `glow` names a part that glows with the light, or parts as MATERIALS
names them (`caps_*`, `lens|diffuser`). `reach`: how far the beam is
drawn, mm."""
from __future__ import annotations

import math
import re

from .materials import matches

KINDS = ("point", "spot", "projector", "laser", "glow")
NAME = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
SCENE = ("room", "haze")      # the timeline's lines for the room's light and the smoke in the air: no light is called so
COLOUR = {"point": "#fff1e0", "spot": "#fff1e0", "projector": "#ffffff", "laser": "#2a4bff", "glow": "#ffffff"}
KEYS = {"kind", "on", "at", "aim", "up", "across", "color", "lumens", "mw", "angle", "soft", "throw", "aspect", "offset",
        "fan", "glow", "reach"}


def _vec(v, what: str) -> list:
    if not (isinstance(v, (list, tuple)) and len(v) == 3 and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                                 and math.isfinite(x) for x in v)):
        raise ValueError(f"{what} is [x, y, z]")
    return [float(x) for x in v]


def _unit(v, what: str) -> list:
    v = _vec(v, what)
    n = math.sqrt(sum(x * x for x in v))
    if n < 1e-9:
        raise ValueError(f"{what} is a direction: not [0, 0, 0]")
    return [x / n for x in v]


def _num(d: dict, key: str, lo: float, hi: float, default=None):
    v = d.get(key, default)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not (lo <= v <= hi):
        raise ValueError(f"{key} is a number from {lo:g} to {hi:g}")
    return float(v)


def _aspect(v) -> float:
    if isinstance(v, str) and re.fullmatch(r"\s*\d+(\.\d+)?\s*:\s*\d+(\.\d+)?\s*", v):
        w, h = (float(x) for x in v.split(":"))
        if w > 0 and h > 0:
            return w / h
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 0.2 <= v <= 5:
        return float(v)
    raise ValueError('aspect is "16:9", "4:3" … or a number (width / height)')


def _square(aim: list, up) -> list:
    """`up` made square to `aim`: the default Z, or Y where the light points straight up or down."""
    u = _unit(up, "up") if up is not None else [0.0, 0.0, 1.0]
    d = sum(a * b for a, b in zip(aim, u))
    if abs(d) > 0.999:
        u = [0.0, 1.0, 0.0] if up is None else None
        if u is None:
            raise ValueError("up runs along aim")
        d = sum(a * b for a, b in zip(aim, u))
    u = [b - d * a for a, b in zip(aim, u)]
    n = math.sqrt(sum(x * x for x in u))
    return [x / n for x in u]


def one(name: str, d: dict, parts: set) -> dict:
    """A light checked and with its defaults, or ValueError saying what is wrong."""
    if not isinstance(d, dict):
        raise ValueError("a light is {kind, at, …}")
    kind = d.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)}")
    extra = set(d) - KEYS
    if extra:
        raise ValueError(f"no {', '.join(sorted(extra))} in a light (it has {', '.join(sorted(KEYS))})")
    out = {"name": name, "kind": kind}
    if d.get("on") is not None:
        if not isinstance(d["on"], str) or (parts and d["on"] not in parts):
            raise ValueError(f"on: there is no part {d['on']!r}")
        out["on"] = d["on"]
    if d.get("glow") is not None:      # a part, or parts as MATERIALS names them: caps_*, diffuser|lens_?
        if not isinstance(d["glow"], str) or (parts and not any(matches(d["glow"], q) for q in parts)):
            raise ValueError(f"glow: no part is {d['glow']!r}")
        out["glow"] = d["glow"]
    color = d.get("color", COLOUR[kind])
    if not (isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color)):
        raise ValueError("color is #rrggbb")
    out["color"] = color.lower()
    if kind == "glow":
        if "glow" not in out:
            raise ValueError("a glow names the part that glows (glow)")
        if d.get("at") is not None:
            out["at"] = _vec(d["at"], "at")
    else:
        out["at"] = _vec(d.get("at"), "at")
    if kind in ("spot", "projector", "laser"):
        out["aim"] = _unit(d.get("aim"), "aim")
    if kind == "laser":
        out["mw"] = _num(d, "mw", 0.1, 10_000, 50)
        out["fan"] = _num(d, "fan", 0, 170, 0)
        if out["fan"]:
            across = _square(out["aim"], d.get("across", d.get("up")))
            out["across"] = across
    else:
        out["lumens"] = _num(d, "lumens", 1, 200_000, 800 if kind != "projector" else 3000)
    if kind == "spot":
        out["angle"] = _num(d, "angle", 0.5, 170, 30)
        out["soft"] = _num(d, "soft", 0, 1, 0.2)
        omega = 2 * math.pi * (1 - math.cos(math.radians(out["angle"] / 2)))      # the beam's solid angle
        out["candela"] = round(out["lumens"] / omega, 1)
    if kind == "projector":
        out["throw"] = _num(d, "throw", 0.2, 5, 1.5)
        out["aspect"] = _aspect(d.get("aspect", "16:9"))
        out["offset"] = _num(d, "offset", -1, 1, 0)
        out["up"] = _square(out["aim"], d.get("up"))
        half_w = 0.5 / out["throw"]                     # tan of half the picture's width, seen from the lens
        half_h = half_w / out["aspect"]
        out["picture"] = {"width_at_1m": round(2 * half_w * 1000, 1), "height_at_1m": round(2 * half_h * 1000, 1)}
        out["candela"] = round(out["lumens"] / (4 * half_w * half_h), 1)
    if kind == "point":
        out["candela"] = round(out["lumens"] / (4 * math.pi), 1)
    out["reach"] = _num(d, "reach", 10, 50_000, 6000 if kind in ("projector", "laser") else 3000)
    out["soft"] = out.get("soft", 0.2 if kind != "laser" else 0.0)
    return out


def clean(lights, parts) -> tuple[list, list]:
    """(the lights checked, what is wrong with the others), from the Note's LIGHTS and the names of its parts."""
    if not lights:
        return [], []
    if not isinstance(lights, dict):
        return [], ["LIGHTS is {name: {kind, at, …}}"]
    out, problems, parts = [], [], set(parts or ())
    for name, d in list(lights.items())[:32]:
        if not NAME.match(str(name)) or name in SCENE:
            problems.append(f"light {name!r}: a name is lowercase letters, digits and _, not room or haze")
            continue
        try:
            out.append(one(name, d, parts))
        except ValueError as e:
            problems.append(f"light {name}: {e}")
    if len(lights) > 32:
        problems.append("at most 32 lights")
    return out, problems
