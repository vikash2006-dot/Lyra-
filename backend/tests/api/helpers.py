import io
import struct
import wave


def make_wav(seconds: float = 0.5, rate: int = 16000, seed: int = 0) -> bytes:
    """Small valid 16-bit PCM mono WAV (unique per seed so duplicate detection can be tested)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = int(seconds * rate)
        w.writeframes(b"".join(struct.pack("<h", ((i * (seed + 7)) % 2000) - 1000) for i in range(frames)))
    return buf.getvalue()
