"""The Note: one Python file per part.

Read here statically (ast): the docstring is the intent, PARAMS the numbers people
change, TAGS the named features, build() the geometry; in an assembly, JOINTS and GROUND
say how its parts may still move (monet/joints.py). A Note is only ever *run* in
the runner subprocess, never imported into the server.
"""
import ast
import hashlib
import json
import re

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


def _literal(node):
    """A literal dict, also when written as dict(a=1, b=2)."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict" and not node.args:
        return {k.arg: ast.literal_eval(k.value) for k in node.keywords}
    return ast.literal_eval(node)


def parse(source: str) -> dict:
    """What a Note says about itself, without running it."""
    out = {"doc": "", "params": {}, "tags": {}, "joints": {}, "ground": None, "tips": {}, "placed": {}, "is_note": False, "error": None}
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        out["error"] = f"syntax error, line {e.lineno}: {e.msg}"
        return out
    out["doc"] = ast.get_docstring(tree) or ""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "build":
            out["is_note"] = True
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("PARAMS", "TAGS"):
                try:
                    out[name.lower()] = _literal(node.value)
                except (ValueError, TypeError, SyntaxError):
                    # PARAMS may come from a shared module (the build reports them); TAGS are rewritten when the
                    # user tags a face in the canvas, so they have to be readable without running anything
                    if name == "TAGS":
                        out["error"] = "TAGS must be a plain literal (no expressions): it is read and rewritten without running the Note"
            elif name in ("JOINTS", "GROUND", "TIPS", "PLACED"):
                try:
                    out[name.lower()] = _literal(node.value)
                except (ValueError, TypeError, SyntaxError):
                    out["error"] = f"{name} must be a plain literal (no expressions): it is read and rewritten without running the Note"
    return out


def _lit(v) -> str:
    if isinstance(v, dict):
        return "{" + ", ".join(f"{json.dumps(str(k))}: {_lit(x)}" for k, x in v.items()) + "}"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_lit(x) for x in v) + "]"
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    return repr(v)


def format_tags(tags: dict) -> str:
    if not tags:
        return "TAGS = {}"
    rows = "".join(f"    {json.dumps(k)}: {_lit(v)},\n" for k, v in tags.items())
    return "TAGS = {\n" + rows + "}"


def _replace(source: str, name: str, block: list) -> str:
    """The Note with the assignment to `name` replaced by these lines (put in before build() where there is none)."""
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            lines[node.lineno - 1:node.end_lineno] = block
            break
    else:
        at = next((n.lineno - 1 for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build"), len(lines))
        lines[at:at] = block + ["", ""]
    return "\n".join(lines) + "\n"


def set_tags(source: str, tags: dict) -> str:
    """The Note with its TAGS replaced. Everything else stays as written."""
    return _replace(source, "TAGS", format_tags(tags).splitlines())


def format_joints(joints: dict) -> str:
    if not joints:
        return "JOINTS = {}"
    rows = "".join(f"    {json.dumps(k)}: {_lit(v)},\n" for k, v in joints.items())
    return "JOINTS = {\n" + rows + "}"


def set_joints(source: str, joints: dict, ground=None) -> str:
    """The Note with its JOINTS (and GROUND) replaced. Everything else stays as written."""
    if ground is not None:
        source = _replace(source, "GROUND", [f"GROUND = {_lit(ground)}"])
    return _replace(source, "JOINTS", format_joints(joints).splitlines())


# what the canvas rewrites (and the server works out again from a build without running it)
LITERALS = ("TAGS", "JOINTS", "GROUND", "TIPS")


def geometry_key(source: str) -> str:
    """The Note's source as far as its shape is concerned: its code as Python reads it (not its layout or comments),
    with its TAGS, JOINTS, GROUND and TIPS left out, so tagging a face or making a joint keeps the build current. One
    that anything in the Note reads (a sketch tag that build() cuts, say) is kept in: then changing it changes the
    shape, and the agent has to build again."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return hashlib.sha256(source.encode()).hexdigest()
    read = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    tree.body = [node for node in tree.body
                 if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                         and node.targets[0].id in LITERALS and node.targets[0].id not in read)]
    return hashlib.sha256(ast.dump(tree).encode()).hexdigest()


def dep_key(name: str, data: bytes, note: str) -> str:
    """What a build records of one project file it read: the Note's own file by its geometry_key, every other one
    (a module, or a Note an assembly imports) whole."""
    if name == f"{note}.py":
        return geometry_key(data.decode("utf-8", "replace"))
    return hashlib.sha256(data).hexdigest()


def literals_key(source: str) -> str:
    """The Note's TAGS, JOINTS, GROUND and TIPS as they are: what a build's tags and joints were found for."""
    p = parse(source)
    return hashlib.sha256(json.dumps([p["tags"], p["joints"], p["ground"], p["tips"]], sort_keys=True).encode()).hexdigest()


def format_placed(placed: dict) -> str:
    if not placed:
        return "PLACED = {}"
    rows = "".join(f"    {json.dumps(k)}: {_lit(v)},\n" for k, v in placed.items())
    return "PLACED = {\n" + rows + "}"


def set_placed(source: str, placed: dict) -> str:
    """The Note with its PLACED (the instances of other Notes put at its snap points) replaced. build() reads it,
    so the shape changes: the agent builds the Note again."""
    return _replace(source, "PLACED", format_placed(placed).splitlines())


TURNS = (0, 90, 180, 270)
PLACE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def clean_placed(spec) -> dict:
    """One entry of PLACED as the canvas may write it: {"note", "at", "turn"}."""
    if not isinstance(spec, dict):
        raise ValueError("an instance is {note, at, turn}")
    note, at, turn = spec.get("note"), spec.get("at"), spec.get("turn", 0)
    if not isinstance(note, str) or not NAME_RE.match(note):
        raise ValueError("note: the name of the Note to put there")
    if not isinstance(at, str) or not re.match(r"^[A-Za-z0-9_.-]{1,64}$", at):
        raise ValueError("at: the name of a snap point")
    if isinstance(turn, bool) or not isinstance(turn, (int, float)) or int(turn) not in TURNS or turn != int(turn):
        raise ValueError(f"turn is one of {', '.join(map(str, TURNS))} degrees about Z")
    return {"note": note, "at": at, "turn": int(turn)}


def imports(source: str) -> set:
    """The modules a Note imports by name (top level only)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    out = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module.split(".")[0])
    return out
