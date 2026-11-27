"""macOS screen capture that respects Screen Recording permission (never bypasses it)."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from lyra.vision.models import Screenshot


class ScreenPermissionError(Exception):
    """Screen Recording permission has not been granted to the process running LYRA."""


class ScreenCaptureError(Exception):
    pass


PERMISSION_HELP = (
    "Screen Recording permission is required. Open System Settings → Privacy & Security → Screen & System "
    "Audio Recording, enable it for the app running LYRA's backend (Terminal, iTerm, VS Code or Claude), "
    "then restart the backend."
)


def _quartz():
    try:
        import Quartz  # type: ignore

        return Quartz
    except Exception:  # pragma: no cover - non-macOS
        return None


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return 0, 0


class ScreenCaptureService:
    def __init__(self) -> None:
        self._screencapture = shutil.which("screencapture")

    @property
    def supported(self) -> bool:
        return sys.platform == "darwin" and self._screencapture is not None

    def permission_status(self) -> str:
        """granted | denied | unsupported (checks without prompting)."""
        if not self.supported:
            return "unsupported"
        q = _quartz()
        if q is None:
            return "unknown"
        try:
            return "granted" if q.CGPreflightScreenCaptureAccess() else "denied"
        except Exception:
            return "unknown"

    def request_permission(self) -> str:
        """Ask macOS to show its own permission prompt (only on explicit user request)."""
        q = _quartz()
        if q is not None:
            try:
                q.CGRequestScreenCaptureAccess()
            except Exception:
                pass
        return self.permission_status()

    def displays(self) -> list[dict[str, Any]]:
        q = _quartz()
        if q is None:
            return []
        err, ids, count = q.CGGetActiveDisplayList(16, None, None)
        out = []
        for index, did in enumerate(ids[:count], start=1):
            b = q.CGDisplayBounds(did)
            px_w = q.CGDisplayPixelsWide(did)
            mode = q.CGDisplayCopyDisplayMode(did)
            px_w = q.CGDisplayModeGetPixelWidth(mode) if mode is not None else px_w
            out.append({
                "index": index,
                "id": int(did),
                "main": bool(q.CGDisplayIsMain(did)),
                "x": b.origin.x, "y": b.origin.y,
                "width": b.size.width, "height": b.size.height,
                "scale": round(px_w / b.size.width, 3) if b.size.width else 1.0,
            })
        return out

    async def capture(
        self,
        display: int | None = None,
        window_id: int | None = None,
        window_info: dict[str, Any] | None = None,
    ) -> Screenshot:
        """Capture a display (1-based index; default = main) or a specific window."""
        if not self.supported:
            raise ScreenCaptureError("Screen capture is only available on macOS.")
        if self.permission_status() == "denied":
            raise ScreenPermissionError(PERMISSION_HELP)
        fd, path = tempfile.mkstemp(suffix=".png", prefix="lyra-cap-")
        os.close(fd)
        try:
            cmd = [self._screencapture, "-x", "-t", "png"]
            if window_id is not None:
                cmd += ["-o", "-l", str(int(window_id))]
            elif display:
                cmd += ["-D", str(int(display))]
            cmd.append(path)
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
            _, err = await asyncio.wait_for(proc.communicate(), timeout=10)
            data = open(path, "rb").read() if os.path.exists(path) else b""
            if proc.returncode != 0 or not data:
                msg = (err or b"").decode(errors="ignore").strip()
                if "could not create image" in msg.lower():
                    raise ScreenPermissionError(PERMISSION_HELP)
                raise ScreenCaptureError(msg or "Screen capture failed.")
        finally:
            try:
                os.remove(path)  # screenshots are never kept on disk
            except OSError:
                pass

        w, h = png_size(data)
        if window_id is not None and window_info:
            b = window_info.get("bounds") or {}
            pts_w = float(b.get("width") or w) or 1.0
            return Screenshot(png=data, width=w, height=h, origin_x=float(b.get("x", 0)),
                              origin_y=float(b.get("y", 0)), scale=w / pts_w, window=window_info,
                              kind="window")
        disp = next((d for d in self.displays() if (display and d["index"] == display) or (not display and d["main"])), None)
        if disp:
            scale = w / disp["width"] if disp["width"] else disp["scale"]
            return Screenshot(png=data, width=w, height=h, origin_x=disp["x"], origin_y=disp["y"],
                              scale=scale, display_id=disp["id"], kind="display")
        return Screenshot(png=data, width=w, height=h)


async def optimize_for_vision(png: bytes, max_side: int = 1568, quality: int = 80) -> tuple[bytes, str, float]:
    """Downscale + JPEG-encode with macOS `sips`. Returns (bytes, mime, factor image_px→original_px)."""
    sips = shutil.which("sips")
    w, h = png_size(png)
    if not sips or not w:
        return png, "image/png", 1.0
    fd_in, src = tempfile.mkstemp(suffix=".png")
    fd_out, dst = tempfile.mkstemp(suffix=".jpg")
    os.close(fd_in)
    os.close(fd_out)
    try:
        with open(src, "wb") as f:
            f.write(png)
        args = [sips, "-s", "format", "jpeg", "-s", "formatOptions", str(quality)]
        if max(w, h) > max_side:
            args += ["-Z", str(max_side)]
        proc = await asyncio.create_subprocess_exec(*args, src, "--out", dst,
                                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await asyncio.wait_for(proc.wait(), timeout=10)
        data = open(dst, "rb").read()
        if not data:
            return png, "image/png", 1.0
        factor = max(w, h) / max_side if max(w, h) > max_side else 1.0
        return data, "image/jpeg", factor
    except Exception:
        return png, "image/png", 1.0
    finally:
        for p in (src, dst):
            try:
                os.remove(p)
            except OSError:
                pass
