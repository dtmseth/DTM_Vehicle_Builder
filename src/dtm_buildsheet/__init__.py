"""DTM Vehicle Builder application package."""

from importlib.metadata import version, PackageNotFoundError
from .gui_server import main as run_gui

try:
    __version__ = version("dtm-buildsheet")
except PackageNotFoundError:
    __version__ = "dev"

__all__ = ["run_gui", "__version__"]
