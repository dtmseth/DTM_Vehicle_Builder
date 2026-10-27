import ctypes
import sys


if sys.platform == "win32":
    # Keep the pywebview window grouped with the Start-menu/desktop launcher.
    # Windows then pins the launcher shortcut (and its immediate splash) when
    # the user chooses "Pin to taskbar" on the running application.
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "DTM.VehicleBuilder"
        )
    except (AttributeError, OSError):
        pass


from dtm_buildsheet.startup_splash import update_startup_status  # noqa: E402


update_startup_status("Loading DTM components...")

from dtm_buildsheet.gui_server import main  # noqa: E402


if __name__ == "__main__":
    main()
