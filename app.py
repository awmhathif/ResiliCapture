from __future__ import annotations

import ctypes
import faulthandler
import json
import logging
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

from recorder.config import APP_VERSION, app_data_dir
from ui.main_window import MainWindow

__version__ = APP_VERSION
_FAULT_FILE = None


def enable_windows_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _runtime_state_path() -> Path:
    return app_data_dir() / "runtime_state.json"


def _write_runtime_state(clean_shutdown: bool) -> None:
    path = _runtime_state_path()
    payload = {
        "version": __version__,
        "pid": os.getpid(),
        "clean_shutdown": bool(clean_shutdown),
    }
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def configure_crash_log() -> Path:
    global _FAULT_FILE
    data_dir = app_data_dir()
    log_path = data_dir / "application.log"
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s",
        encoding="utf-8",
    )

    try:
        previous = json.loads(_runtime_state_path().read_text(encoding="utf-8"))
        if not previous.get("clean_shutdown", True):
            logging.warning("Previous ResiliCapture run did not record a clean shutdown: %s", previous)
    except (OSError, ValueError, json.JSONDecodeError):
        pass

    _write_runtime_state(False)

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.critical("Uncaught application exception", exc_info=(exc_type, exc_value, exc_traceback))
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    def handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        logging.critical(
            "Uncaught thread exception in %s",
            getattr(args.thread, "name", "unknown"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception

    try:
        _FAULT_FILE = open(data_dir / "native_crash.log", "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_FAULT_FILE, all_threads=True)
    except OSError:
        _FAULT_FILE = None
    return log_path


def install_tk_exception_handler(root: tk.Tk) -> None:
    def report_callback_exception(exc_type, exc_value, exc_traceback) -> None:
        logging.critical("Unhandled Tk callback exception", exc_info=(exc_type, exc_value, exc_traceback))
        try:
            messagebox.showerror(
                "ResiliCapture error",
                "A user-interface error occurred. Recording data is kept in the recovery session when possible. See application.log for details.",
                parent=root,
            )
        except Exception:
            pass

    root.report_callback_exception = report_callback_exception


def main() -> None:
    enable_windows_dpi_awareness()
    configure_crash_log()
    root = tk.Tk()
    install_tk_exception_handler(root)
    icon = Path(__file__).resolve().parent / "assets" / "app.ico"
    if icon.exists():
        try:
            root.iconbitmap(str(icon))
        except tk.TclError:
            pass
    MainWindow(root)
    try:
        root.mainloop()
    finally:
        _write_runtime_state(True)
        if _FAULT_FILE is not None:
            try:
                faulthandler.disable()
                _FAULT_FILE.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
