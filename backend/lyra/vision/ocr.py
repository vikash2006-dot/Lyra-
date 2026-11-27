"""Fast, local OCR using Apple's Vision framework (no network, no API cost)."""

from __future__ import annotations

import asyncio

from lyra.vision.models import OCRLine


def ocr_available() -> bool:
    try:
        import Vision  # type: ignore  # noqa: F401

        return True
    except Exception:
        return False


def _recognize(png: bytes, fast: bool) -> list[OCRLine]:
    import Quartz  # type: ignore
    import Vision  # type: ignore
    from Foundation import NSData  # type: ignore

    data = NSData.dataWithBytes_length_(png, len(png))
    source = Quartz.CGImageSourceCreateWithData(data, None)
    if source is None:
        return []
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if image is None:
        return []
    width, height = Quartz.CGImageGetWidth(image), Quartz.CGImageGetHeight(image)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(1 if fast else 0)  # 0 = accurate, 1 = fast
    request.setUsesLanguageCorrection_(not fast)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
    ok, _err = handler.performRequests_error_([request], None)
    if not ok:
        return []
    lines: list[OCRLine] = []
    for obs in request.results() or []:
        candidates = obs.topCandidates_(1)
        if not candidates:
            continue
        cand = candidates[0]
        box = obs.boundingBox()  # normalized, bottom-left origin
        x = box.origin.x * width
        w = box.size.width * width
        h = box.size.height * height
        y = (1 - box.origin.y - box.size.height) * height
        lines.append(OCRLine(text=str(cand.string()), confidence=float(cand.confidence()), bbox=[x, y, w, h]))
    lines.sort(key=lambda l: (round(l.bbox[1] / 12), l.bbox[0]))
    return lines


async def recognize_text(png: bytes, fast: bool = False) -> list[OCRLine]:
    if not png or not ocr_available():
        return []
    return await asyncio.to_thread(_recognize, png, fast)


def lines_to_text(lines: list[OCRLine]) -> str:
    out, last_row = [], None
    for line in lines:
        row = round(line.bbox[1] / 12)
        if last_row is not None and row == last_row:
            out[-1] += "   " + line.text
        else:
            out.append(line.text)
        last_row = row
    return "\n".join(out)


async def warm_up() -> None:
    """Load Apple's text-recognition model once (first use costs several seconds)."""
    if not ocr_available():
        return
    try:
        from lyra.vision.capture import png_size  # noqa: F401
        tiny = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS"
                b"\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00\x00\x00\x00IEND\xaeB`\x82")
        await recognize_text(tiny)
    except Exception:
        pass
