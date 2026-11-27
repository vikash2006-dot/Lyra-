"""Render synthetic 'screenshots' with real text (AppKit) for OCR/vision tests."""

from __future__ import annotations


def render_screen(items: list[tuple[str, float, float, float]], width: int = 1200, height: int = 760,
                  boxes: list[tuple[float, float, float, float]] | None = None) -> bytes:
    """items: (text, x, y_from_top, font_size). boxes: outlined rectangles (x, y_from_top, w, h)."""
    from AppKit import (  # type: ignore
        NSBitmapImageRep, NSBezierPath, NSColor, NSFont, NSFontAttributeName, NSForegroundColorAttributeName,
        NSGraphicsContext, NSMakeRect, NSPNGFileType, NSString,
    )

    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, width, height, 8, 4, True, False, "NSDeviceRGBColorSpace", 0, 0)
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)
    NSColor.whiteColor().set()
    NSBezierPath.fillRect_(NSMakeRect(0, 0, width, height))
    NSColor.darkGrayColor().set()
    for (x, y, w, h) in boxes or []:
        path = NSBezierPath.bezierPathWithRect_(NSMakeRect(x, height - y - h, w, h))
        path.setLineWidth_(2)
        path.stroke()
    for text, x, y, size in items:
        attrs = {NSFontAttributeName: NSFont.systemFontOfSize_(size),
                 NSForegroundColorAttributeName: NSColor.blackColor()}
        NSString.stringWithString_(text).drawAtPoint_withAttributes_((x, height - y - size * 1.25), attrs)
    NSGraphicsContext.restoreGraphicsState()
    return bytes(rep.representationUsingType_properties_(NSPNGFileType, None))


LOGIN_SCREEN = [
    ("Acme Portal — Sign in", 420, 120, 30),
    ("Email address", 400, 230, 20),
    ("Password", 400, 330, 20),
    ("Error: Invalid password. Please try again.", 400, 420, 20),
    ("Login", 560, 506, 24),
    ("Forgot password?", 520, 600, 18),
]
LOGIN_BOXES = [(400, 260, 400, 44), (400, 360, 400, 44), (520, 495, 140, 50)]
