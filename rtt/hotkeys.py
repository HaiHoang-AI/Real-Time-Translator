"""System-wide hotkeys (Windows) delivered as Qt signals.

A QShortcut only fires while one of *our* windows has keyboard focus, and the
subtitle overlay never takes focus — so the documented Ctrl+Alt+E toggle never
worked while you were watching a video. RegisterHotKey works no matter which
app is in front.

Default bindings (see rtt.app):
    Ctrl+Alt+E  show / hide the control window
    Ctrl+Alt+P  pause / resume translation
    Ctrl+Alt+S  lock / unlock the subtitle overlay (click-through + drag)
"""

from __future__ import annotations

import sys
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312


class GlobalHotkeys(QAbstractNativeEventFilter):
    """Register Win32 hotkeys on the GUI thread and dispatch them to callbacks."""

    def __init__(self) -> None:
        super().__init__()
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_id = 0xB000
        self._installed = False

    def register(self, modifiers: int, key: str, callback: Callable[[], None]) -> bool:
        """Bind e.g. (MOD_CONTROL | MOD_ALT, "E"). Returns False if unavailable/taken."""
        if sys.platform != "win32":
            return False
        import ctypes

        vk = ord(key.upper()) if len(key) == 1 else int(key, 0)
        hk_id = self._next_id
        self._next_id += 1
        # hwnd=None -> WM_HOTKEY is posted to this (GUI) thread's queue.
        ok = ctypes.windll.user32.RegisterHotKey(None, hk_id, modifiers | MOD_NOREPEAT, vk)
        if not ok:
            print(f"[hotkeys] could not register hotkey {key!r} (already used by another app?)")
            return False
        self._callbacks[hk_id] = callback
        if not self._installed:
            QCoreApplication.instance().installNativeEventFilter(self)
            self._installed = True
        return True

    def unregister_all(self) -> None:
        if sys.platform != "win32":
            return
        import ctypes

        for hk_id in list(self._callbacks):
            ctypes.windll.user32.UnregisterHotKey(None, hk_id)
        self._callbacks.clear()

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt API
        if not self._callbacks:
            return False, 0
        et = bytes(event_type) if not isinstance(event_type, (bytes, str)) else event_type
        if isinstance(et, bytes):
            et = et.decode(errors="ignore")
        if et not in ("windows_generic_MSG", "windows_dispatcher_MSG"):
            return False, 0
        from ctypes import wintypes

        msg = wintypes.MSG.from_address(int(message))
        if msg.message == WM_HOTKEY:
            cb = self._callbacks.get(int(msg.wParam))
            if cb is not None:
                try:
                    cb()
                except Exception as exc:  # noqa: BLE001 - never break the event loop
                    print(f"[hotkeys] handler error: {exc}")
                return True, 0
        return False, 0
