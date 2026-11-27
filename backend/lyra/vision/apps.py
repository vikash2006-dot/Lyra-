"""Active application and window awareness (macOS)."""

from __future__ import annotations

from typing import Any


def frontmost_app() -> dict[str, Any] | None:
    """Name/bundle/pid of the frontmost app. Needs no special permission."""
    try:
        from AppKit import NSWorkspace  # type: ignore

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        return {
            "name": str(app.localizedName() or ""),
            "bundle_id": str(app.bundleIdentifier() or ""),
            "pid": int(app.processIdentifier()),
        }
    except Exception:
        return None


def windows(on_screen_only: bool = True) -> list[dict[str, Any]]:
    """Normal app windows, front-to-back. Titles require Screen Recording permission."""
    try:
        import Quartz  # type: ignore
    except Exception:
        return []
    opts = Quartz.kCGWindowListExcludeDesktopElements
    if on_screen_only:
        opts |= Quartz.kCGWindowListOptionOnScreenOnly
    out = []
    for w in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []:
        if int(w.get("kCGWindowLayer", 1)) != 0:
            continue
        b = w.get("kCGWindowBounds") or {}
        width, height = float(b.get("Width", 0)), float(b.get("Height", 0))
        if width < 80 or height < 60:
            continue
        out.append({
            "id": int(w.get("kCGWindowNumber", 0)),
            "app": str(w.get("kCGWindowOwnerName") or ""),
            "pid": int(w.get("kCGWindowOwnerPID", 0)),
            "title": str(w.get("kCGWindowName") or "") or None,
            "bounds": {"x": float(b.get("X", 0)), "y": float(b.get("Y", 0)), "width": width, "height": height},
        })
    return out


def focused_window_title_ax(pid: int) -> str | None:
    """Window title via Accessibility (works when Accessibility permission is granted)."""
    try:
        import ApplicationServices as AX  # type: ignore

        app = AX.AXUIElementCreateApplication(pid)
        err, win = AX.AXUIElementCopyAttributeValue(app, "AXFocusedWindow", None)
        if err or win is None:
            return None
        err, title = AX.AXUIElementCopyAttributeValue(win, "AXTitle", None)
        return str(title) if not err and title else None
    except Exception:
        return None


def active_window() -> dict[str, Any] | None:
    """Frontmost app plus its top window (id, title when available, bounds)."""
    app = frontmost_app()
    if not app:
        return None
    win = next((w for w in windows() if w["pid"] == app["pid"]), None)
    title = (win or {}).get("title") or focused_window_title_ax(app["pid"])
    return {
        "app": app["name"],
        "bundle_id": app["bundle_id"],
        "pid": app["pid"],
        "window_id": (win or {}).get("id"),
        "title": title,
        "bounds": (win or {}).get("bounds"),
    }


def accessibility_trusted() -> bool:
    try:
        import ApplicationServices as AX  # type: ignore

        return bool(AX.AXIsProcessTrusted())
    except Exception:
        return False
