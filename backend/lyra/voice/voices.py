"""LYRA's voice identity: natural female voice selection and speech-friendly text.

macOS ships many voices and the system default is often male (e.g. "Rishi"). LYRA always
asks for an explicit female voice, preferring the most natural one installed:
premium/enhanced neural voices first (downloadable in System Settings -> Accessibility ->
Spoken Content -> System Voice -> Manage Voices), then the classic natural voices.
"""

from __future__ import annotations

from functools import lru_cache
import re
import shutil
import subprocess

# Most natural first. Base names are matched against installed voices, preferring
# "(Premium)" over "(Enhanced)" over the compact variant.
FEMALE_VOICE_PREFERENCE: tuple[str, ...] = (
    "Ava", "Zoe", "Allison", "Susan", "Isha", "Veena", "Kate", "Serena", "Samantha",
    "Nicky", "Karen", "Moira", "Tessa", "Tara", "Fiona", "Catherine", "Lekha",
)
# Female voices that sound robotic/novelty — only used if nothing better exists.
FEMALE_FALLBACK_VOICES: tuple[str, ...] = ("Kathy", "Flo", "Sandy", "Shelley", "Victoria")
KNOWN_FEMALE = frozenset(FEMALE_VOICE_PREFERENCE + FEMALE_FALLBACK_VOICES)

_QUALITY_RANK = {"premium": 0, "enhanced": 1}


def _parse_voices(output: str) -> list[dict[str, str]]:
    voices = []
    for line in output.splitlines():
        head = line.split("#", 1)[0].rstrip()
        m = re.match(r"^(.*\S)\s+([a-z]{2}_[A-Z]{2,3})$", head)
        if m:
            voices.append({"name": m.group(1).strip(), "locale": m.group(2)})
    return voices


@lru_cache(maxsize=1)
def installed_voices() -> tuple[dict[str, str], ...]:
    say = shutil.which("say")
    if not say:
        return ()
    try:
        out = subprocess.run([say, "-v", "?"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ()
    seen: set[str] = set()
    unique = []
    for v in _parse_voices(out):
        if v["name"] not in seen:
            seen.add(v["name"])
            unique.append(v)
    return tuple(unique)


def base_name(voice_name: str) -> str:
    return voice_name.split(" (", 1)[0].strip()


def is_female_voice(voice_name: str) -> bool:
    return base_name(voice_name) in KNOWN_FEMALE


def female_voices(voices: tuple[dict[str, str], ...] | None = None) -> list[dict[str, str]]:
    """Installed English female voices, best first."""
    pool = installed_voices() if voices is None else voices
    order = {n: i for i, n in enumerate(FEMALE_VOICE_PREFERENCE + FEMALE_FALLBACK_VOICES)}

    def rank(v: dict[str, str]) -> tuple[int, int, int]:
        name = v["name"]
        quality = next((r for k, r in _QUALITY_RANK.items() if k in name.lower()), 2)
        english = 0 if v["locale"].startswith("en_") else 1
        return (order.get(base_name(name), 999), quality, english)

    return sorted((v for v in pool if is_female_voice(v["name"])), key=rank)


def select_female_voice(preferred: str | None = None, voices: tuple[dict[str, str], ...] | None = None) -> str | None:
    """Return the voice name LYRA should use. Honours an installed preferred voice."""
    pool = installed_voices() if voices is None else voices
    names = {v["name"] for v in pool}
    if preferred and preferred in names:
        return preferred
    ranked = female_voices(pool)
    english = [v for v in ranked if v["locale"].startswith("en_")]
    best = (english or ranked or [None])[0]
    return best["name"] if best else None


# ---------------------------------------------------------------------------
# Speech-friendly text
# ---------------------------------------------------------------------------

_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def prepare_speech_text(text: str) -> str:
    """Turn chat-formatted text into something that sounds natural when spoken."""
    t = text or ""
    t = re.sub(r"```.*?```", " I've put the code in the chat. ", t, flags=re.DOTALL)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\((?:https?://)[^)]+\)", r"\1", t)
    t = re.sub(r"https?://\S+", "this link", t)
    t = re.sub(r"(\*\*|__|\*|_|~~)(.+?)\1", r"\2", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+(.*)$", lambda m: m.group(1).rstrip(".:;") + ".", t, flags=re.MULTILINE)
    t = _EMOJI_RE.sub("", t)
    t = t.replace("—", ", ").replace("–", ", ").replace("&", " and ")
    t = re.sub(r"\s*\n+\s*", " ", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    t = re.sub(r"([.!?])(?:\s*[.!?])+", r"\1", t)
    return t.strip()


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def split_for_speech(text: str, first_max: int = 140, max_chars: int = 260) -> list[str]:
    """Split text into speakable chunks at sentence boundaries.

    The first chunk is kept short so speech starts quickly; later chunks merge
    several sentences so there are few gaps and delivery stays continuous.
    """
    sentences = [s.strip() for s in _SENTENCE_END.split(text.strip()) if s.strip()]
    chunks: list[str] = []
    buf = ""
    for sentence in sentences:
        limit = first_max if not chunks else max_chars
        if buf and len(buf) + 1 + len(sentence) > limit:
            chunks.append(buf)
            buf = sentence
        else:
            buf = f"{buf} {sentence}".strip()
        if not chunks and len(buf) >= first_max * 0.5:
            chunks.append(buf)
            buf = ""
    if buf:
        chunks.append(buf)
    return chunks
