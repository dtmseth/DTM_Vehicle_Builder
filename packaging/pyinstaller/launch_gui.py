from dtm_buildsheet.startup_splash import update_startup_status


update_startup_status("Loading DTM components...")

from dtm_buildsheet.gui_server import main  # noqa: E402


if __name__ == "__main__":
    main()
