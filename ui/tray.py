from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable


class TrayController:
    """Small pystray wrapper that keeps tray callbacks out of Tk's thread.

    pystray is imported lazily so source/tests can still start on systems where
    the optional desktop integration is unavailable. Every menu callback is
    marshalled through ``dispatch`` (normally ``root.after(0, callback)``).
    """

    def __init__(
        self,
        *,
        icon_path: Path,
        dispatch: Callable[[Callable[[], None]], None],
        on_show: Callable[[], None],
        on_toggle_pause: Callable[[], None],
        on_stop: Callable[[], None],
        on_open_recordings: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self.icon_path = icon_path
        self.dispatch = dispatch
        self.on_show = on_show
        self.on_toggle_pause = on_toggle_pause
        self.on_stop = on_stop
        self.on_open_recordings = on_open_recordings
        self.on_exit = on_exit
        self.icon = None
        self.available = False
        self._logger = logging.getLogger("resilicapture.tray")

    def _dispatch(self, callback: Callable[[], None]) -> None:
        try:
            self.dispatch(callback)
        except Exception:
            self._logger.exception("Could not dispatch tray callback")

    def start(self) -> bool:
        if self.icon is not None:
            return self.available
        try:
            import pystray
            from PIL import Image

            image = Image.open(self.icon_path) if self.icon_path.exists() else Image.new("RGB", (64, 64), "white")
            menu = pystray.Menu(
                pystray.MenuItem("Show ResiliCapture", lambda _icon, _item: self._dispatch(self.on_show), default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Pause / Resume", lambda _icon, _item: self._dispatch(self.on_toggle_pause)),
                pystray.MenuItem("Stop & Save", lambda _icon, _item: self._dispatch(self.on_stop)),
                pystray.MenuItem("Open Recordings", lambda _icon, _item: self._dispatch(self.on_open_recordings)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit ResiliCapture", lambda _icon, _item: self._dispatch(self.on_exit)),
            )
            self.icon = pystray.Icon("ResiliCapture", image, "ResiliCapture", menu)
            self.icon.run_detached()
            self.available = True
            self._logger.info("System tray integration started")
            return True
        except Exception as exc:
            self.icon = None
            self.available = False
            self._logger.warning("System tray integration unavailable: %s", exc)
            return False

    def set_title(self, title: str) -> None:
        if self.icon is None:
            return
        try:
            self.icon.title = title
            self.icon.update_menu()
        except Exception:
            self._logger.exception("Could not update tray status")

    def notify(self, title: str, message: str) -> None:
        if self.icon is None:
            return
        try:
            # pystray's API names the message first and title second.
            self.icon.notify(message, title)
        except Exception:
            self._logger.debug("Tray notification unavailable", exc_info=True)

    def stop(self) -> None:
        icon = self.icon
        self.icon = None
        self.available = False
        if icon is None:
            return
        try:
            icon.stop()
        except Exception:
            self._logger.exception("Could not stop system tray integration")
