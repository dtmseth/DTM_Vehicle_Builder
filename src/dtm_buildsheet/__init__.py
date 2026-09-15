"""DTM Vehicle Builder application package."""

from importlib.metadata import version, PackageNotFoundError


def run_gui(*args, **kwargs):
    # Keep package import side-effect free so headless startup can select its
    # workspace before modules capture AppPaths defaults.
    from .gui_server import main
    return main(*args, **kwargs)

try:
    __version__ = version("dtm-buildsheet")
except PackageNotFoundError:
    __version__ = "dev"

__all__ = ["run_gui", "__version__"]
