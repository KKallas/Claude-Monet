"""The Note: one Python file per part.

Read here statically (ast): the docstring is the intent, PARAMS the numbers people
change, TAGS the named features, build() the geometry. A Note is only ever *run* in
the runner subprocess, never imported into the server.
"""
import ast
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
    out = {"doc": "", "params": {}, "tags": {}, "is_note": False, "error": None}
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


def set_tags(source: str, tags: dict) -> str:
    """The Note with its TAGS replaced. Everything else stays as written."""
    tree = ast.parse(source)
    lines = source.splitlines()
    block = format_tags(tags).splitlines()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TAGS" for t in node.targets):
            lines[node.lineno - 1:node.end_lineno] = block
            break
    else:
        at = next((n.lineno - 1 for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build"), len(lines))
        lines[at:at] = block + ["", ""]
    return "\n".join(lines) + "\n"
