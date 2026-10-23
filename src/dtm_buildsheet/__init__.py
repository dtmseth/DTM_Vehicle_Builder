"""DTM Vehicle Builder application package."""

from .version import get_app_version


def run_gui(*args, **kwargs):
    # Keep package import side-effect free so headless startup can select its
    # workspace before modules capture AppPaths defaults.
    from .gui_server import main
    return main(*args, **kwargs)

__version__ = get_app_version()

__all__ = ["run_gui", "__version__"]
