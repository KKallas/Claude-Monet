"""What a build needs, loaded once: imported by the fork server, so that every build starts from a process that
already has the CAD kernel in it instead of spending seconds loading it (monet/workspace.py)."""
import build123d  # noqa: F401
import OCP.BRepAdaptor  # noqa: F401
import OCP.BRepGProp  # noqa: F401
import OCP.BRepMesh  # noqa: F401
import OCP.IntCurvesFace  # noqa: F401

from . import runner, semmelweis, tags  # noqa: F401
