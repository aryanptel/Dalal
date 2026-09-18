"""
Launcher for the packaged Dalal AI UI.

The exe is built windowed (``console=False``), which means the process has no
console and, on Windows, ``sys.stdin`` is ``None``.  Streamlit's first run on a
machine that has never run it before prints a welcome banner and *prompts for an
email address on stdin*.  With no stdin that prompt either raises or blocks
forever with nothing on screen — which is why a build that ran fine on the
development machine (where ``~/.streamlit/credentials.toml`` already existed)
appeared to do nothing at all on a clean PC.

Everything below exists to make the first run on a clean machine behave exactly
like the hundredth run on the development machine.
"""

import os
import sys
import subprocess
import traceback

from utils.paths import is_frozen, get_bundle_dir, get_logs_dir
from utils.logger import logger


def show_error_dialog(error_msg: str) -> None:
    """Last-resort visible error, since a windowed exe has nowhere to print."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Dalal AI - Fatal Error",
            "The application encountered a fatal error and must close.\n\n"
            f"{error_msg}",
        )
        root.destroy()
    except Exception:
        pass


def ensure_streamlit_credentials() -> None:
    """
    Pre-seed ``~/.streamlit/credentials.toml`` so Streamlit never prompts.

    Streamlit only asks for an email when this file is absent.  Writing an empty
    address is the documented way to skip it non-interactively.
    """
    try:
        cred_dir = os.path.join(os.path.expanduser("~"), ".streamlit")
        cred_path = os.path.join(cred_dir, "credentials.toml")
        if os.path.exists(cred_path):
            return
        os.makedirs(cred_dir, exist_ok=True)
        with open(cred_path, "w", encoding="utf-8") as fh:
            fh.write('[general]\nemail = ""\n')
        logger.info(f"Created {cred_path} to skip Streamlit's first-run prompt.")
    except Exception as exc:
        # Not fatal on its own; the env var below is a second line of defence.
        logger.warning(f"Could not write Streamlit credentials file: {exc}")


def configure_streamlit_env() -> None:
    """Pin the Streamlit settings a frozen, windowed app needs."""
    env = {
        # Never prompt, never phone home.
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        # The source watcher walks module __file__ paths, which point inside the
        # PyInstaller archive and are not real files.
        "STREAMLIT_SERVER_FILE_WATCHER_TYPE": "none",
        "STREAMLIT_GLOBAL_DEVELOPMENT_MODE": "false",
        # Keep the toolbar out of an end-user app.
        "STREAMLIT_CLIENT_TOOLBAR_MODE": "minimal",
    }
    for key, value in env.items():
        os.environ.setdefault(key, value)


def ensure_stdio() -> None:
    """
    Give the process usable stdio.

    A windowed build has ``sys.stdin is None``; any library that touches it
    (click, Streamlit's prompt) raises ``AttributeError`` deep in a traceback
    the user never sees.
    """
    if sys.stdin is None:
        try:
            sys.stdin = open(os.devnull, "r", encoding="utf-8")
        except Exception:
            pass
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except Exception:
                pass


def main() -> None:
    try:
        logger.info("Starting Dalal AI UI...")

        script_path = os.path.join(get_bundle_dir(), "dalal_ai", "ui", "app.py")
        if not os.path.isfile(script_path):
            raise FileNotFoundError(
                f"UI script not found at:\n  {script_path}\n\n"
                "The build is incomplete — dalal_ai/ui/app.py was not packaged."
            )

        configure_streamlit_env()
        ensure_streamlit_credentials()

        if is_frozen():
            # console=False hides stdout/stderr, so capture them to a file the
            # user can be pointed at.
            log_path = os.path.join(get_logs_dir(), "crash_log.txt")
            try:
                stream = open(log_path, "w", encoding="utf-8", buffering=1)
                sys.stdout = stream
                sys.stderr = stream
            except Exception as exc:
                logger.warning(f"Could not open crash log {log_path}: {exc}")
            ensure_stdio()

            from streamlit.web import cli as stcli

            sys.argv = [
                "streamlit",
                "run",
                script_path,
                "--global.developmentMode=false",
                # headless=false so the browser opens by itself; the prompt it
                # would otherwise trigger is already defused above.
                "--server.headless=false",
                "--server.fileWatcherType=none",
                "--browser.gatherUsageStats=false",
            ]

            logger.info(f"Running Streamlit via PyInstaller bundle: {sys.argv}")
            sys.exit(stcli.main())
        else:
            logger.info("Running Streamlit from source via subprocess...")
            sys.exit(
                subprocess.call(
                    [
                        sys.executable, "-m", "streamlit", "run", script_path,
                        "--server.fileWatcherType=none",
                        "--browser.gatherUsageStats=false",
                    ]
                )
            )
    except SystemExit:
        raise
    except Exception:
        error_msg = traceback.format_exc()
        logger.critical(f"Fatal error in run_ui.py: {error_msg}")
        if is_frozen():
            show_error_dialog(error_msg)
        sys.exit(1)


if __name__ == "__main__":
    main()
