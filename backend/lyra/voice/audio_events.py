"""Non-speech audio event detection (currently: coughs) on recorded utterances.

Speech-to-text drops non-speech sounds, so coughs are detected from the raw signal.
A cough is an *explosive*, *noisy*, *short* burst: energy rises within a few tens of
milliseconds, the sound is broadband (high zero-crossing rate, unlike voiced speech),
it lasts roughly 0.1–0.8 s, decays quickly, and is usually separated from speech by
brief silence. Each criterion contributes to a confidence score; only confident events
are reported. This is a heuristic signal detector — never a diagnosis.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass
import io
import math
import sys
import wave

FRAME_MS = 20


@dataclass(frozen=True)
class AudioEvent:
    type: str
    start_s: float
    duration_s: float
    confidence: float

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "start_s": round(self.start_s, 2),
            "duration_s": round(self.duration_s, 2),
            "confidence": round(self.confidence, 2),
        }


def _read_wav(data: bytes) -> tuple[list[float], int] | None:
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            if w.getsampwidth() != 2:
                return None
            channels, rate = w.getnchannels(), w.getframerate()
            raw = w.readframes(w.getnframes())
    except (wave.Error, EOFError):
        return None
    samples = array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % 2])
    if sys.byteorder == "big":
        samples.byteswap()
    if channels > 1:
        samples = samples[::channels]
    return [s / 32768.0 for s in samples], rate


def _frames(samples: list[float], rate: int) -> tuple[list[float], list[float]]:
    n = max(1, int(rate * FRAME_MS / 1000))
    rms, zcr = [], []
    for i in range(0, len(samples) - n + 1, n):
        f = samples[i : i + n]
        rms.append(math.sqrt(sum(x * x for x in f) / n))
        crossings = sum(1 for a, b in zip(f, f[1:]) if (a >= 0) != (b >= 0))
        zcr.append(crossings / n)
    return rms, zcr


def detect_coughs(data: bytes, min_confidence: float = 0.7) -> list[AudioEvent]:
    """Return confident cough events found in a WAV clip (16-bit PCM)."""
    parsed = _read_wav(data)
    if not parsed:
        return []
    samples, rate = parsed
    if len(samples) < rate * 0.15:
        return []
    rms, zcr = _frames(samples, rate)
    if not rms:
        return []
    noise = sorted(rms)[max(0, len(rms) // 5 - 1)]
    threshold = max(noise * 5.0, 0.02)
    active = [r > threshold for r in rms]

    # Group active frames into bursts, bridging single-frame dips.
    segments: list[tuple[int, int]] = []
    i = 0
    while i < len(active):
        if active[i]:
            j = i
            while j + 1 < len(active) and (active[j + 1] or (j + 2 < len(active) and active[j + 2])):
                j += 1
            segments.append((i, j))
            i = j + 1
        else:
            i += 1

    frame_s = FRAME_MS / 1000
    events: list[AudioEvent] = []
    for start, end in segments:
        length = end - start + 1
        duration = length * frame_s
        if not 0.1 <= duration <= 0.8:
            continue
        seg = rms[start : end + 1]
        peak_idx = max(range(length), key=seg.__getitem__)
        peak = seg[peak_idx]
        before = rms[start - 1] if start > 0 else noise
        attack_fast = peak_idx <= 3 and peak_idx <= max(1, int(length * 0.4))
        explosive = peak / max(before, 1e-4) >= 6.0
        tail = seg[int(length * 2 / 3) :] or seg[-1:]
        decays = max(tail) <= peak * 0.55
        noisy = sum(zcr[start : end + 1]) / length >= 0.12
        if not (attack_fast and explosive and decays and noisy):
            continue  # core shape of a cough is missing
        quiet_before = all(not a for a in active[max(0, start - 5) : start])
        quiet_after = all(not a for a in active[end + 1 : end + 5])
        confidence = 0.6
        confidence += 0.15 if quiet_before else 0.0
        confidence += 0.1 if quiet_after else 0.0
        confidence += 0.1 if peak / max(noise, 1e-4) >= 20 else 0.0
        confidence += 0.05 if duration <= 0.5 else 0.0
        if confidence >= min_confidence:
            events.append(AudioEvent("cough", start * frame_s, duration, min(confidence, 0.95)))
    return events
