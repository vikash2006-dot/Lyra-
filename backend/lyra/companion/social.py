"""Social intent detection (greetings, farewells, thanks, ...) and LYRA's natural replies.

Greetings and farewells used to fall straight through to the LLM, which sometimes
answered "Hello" with a farewell phrase picked up from memory. This module classifies
short purely-social messages deterministically so the right *kind* of reply is
guaranteed, while still varying the wording so LYRA never sounds templated.

Only messages that are *purely* social are answered here. "Hi Lyra, open YouTube" is a
task and is left to the planner; "hello, how does DNS work?" goes to the AI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import itertools
import re

WAKE_RE = re.compile(r"\b(?:lyra|lira|laira|leera)\b[,!.]?", re.IGNORECASE)
_FILLER_RE = re.compile(r"\b(?:hey|hi|hello|ok|okay|so|well|um+|uh+|oh|please|boss|there|dear)\b", re.IGNORECASE)

GREETING_PATTERNS = (
    r"(?:hello|hi|hey|hiya|howdy|yo|namaste|hola|greetings)(?: there)?",
    r"good (?:morning|afternoon|evening|day)",
    r"(?:hey|hi|hello)?\s*(?:what'?s up|wassup|sup)",
)
HOW_ARE_YOU_PATTERNS = (
    r"how (?:are|r) (?:you|u)(?: doing| today| now)?",
    r"how(?:'s| is) (?:it going|your day|everything)",
    r"how have you been",
    r"are you (?:ok|okay|good|fine|alright)",
)
FAREWELL_PATTERNS = (
    r"(?:good ?)?bye(?: bye)?",
    r"see (?:you|ya|u)(?: later| soon| tomorrow| around)?",
    r"(?:talk|speak) (?:to you )?(?:later|soon|tomorrow)",
    r"catch you later",
    r"take care",
    r"(?:i'?m|i am) (?:leaving|going|off|heading out|done for (?:the day|today|now))(?: now)?",
    r"(?:i (?:have|need|gotta|got) to|i'?ll) go(?: now)?",
    r"that'?s all(?: for (?:now|today))?",
    r"good ?night",
    r"(?:end|close|stop) (?:the )?(?:chat|conversation|session)",
)
THANKS_PATTERNS = (
    r"(?:thank you|thanks|thank u|thx|ty|much appreciated|appreciate it)(?: so much| a lot| very much)?",
    r"(?:great|good|nice|perfect|awesome) (?:job|work)(?:,? thanks)?",
)
COMPLIMENT_PATTERNS = (
    r"(?:you(?:'re| are)|ur) (?:amazing|awesome|great|the best|so (?:smart|helpful|sweet|kind)|smart|helpful|brilliant|wonderful|cute|lovely)",
    r"i (?:love|like) (?:you|talking to you|your voice)",
    r"good girl",
)
ACK_PATTERNS = (r"(?:ok|okay|alright|cool|got it|nice|great|perfect|fine|sure)",)


def _full(patterns: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"^(?:" + "|".join(patterns) + r")$", re.IGNORECASE)


_GREETING = _full(GREETING_PATTERNS)
_HOW_ARE_YOU = _full(HOW_ARE_YOU_PATTERNS)
_FAREWELL = _full(FAREWELL_PATTERNS)
_THANKS = _full(THANKS_PATTERNS)
_COMPLIMENT = _full(COMPLIMENT_PATTERNS)
_ACK = _full(ACK_PATTERNS)
_GREETING_PREFIX = re.compile(r"^(?:" + "|".join(GREETING_PATTERNS) + r")\b", re.IGNORECASE)


def normalize(text: str) -> str:
    t = WAKE_RE.sub(" ", text or "")
    t = re.sub(r"[^\w\s']", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def _strip_fillers(t: str) -> str:
    return re.sub(r"\s+", " ", _FILLER_RE.sub(" ", t)).strip()


@dataclass(frozen=True)
class SocialIntent:
    """kind: greeting | greeting_how_are_you | how_are_you | farewell | thanks | compliment | acknowledgement."""

    kind: str
    time_of_day: str | None = None  # morning | afternoon | evening | night (for "good X" greetings)


def detect_social_intent(text: str) -> SocialIntent | None:
    """Classify a message that is *only* social chatter. Returns None for anything else."""
    t = normalize(text)
    if not t or len(t.split()) > 9:
        return None

    tod = None
    m = re.search(r"good ?(morning|afternoon|evening|night)", t)
    if m:
        tod = m.group(1)

    # "good night" is a farewell; "good morning/afternoon/evening" are greetings.
    if tod == "night" and (_FAREWELL.match(t) or _FAREWELL.match(_strip_fillers(t)) or t in ("good night", "goodnight")):
        return SocialIntent("farewell", "night")

    # Greeting followed by "how are you" — "hi lyra how are you".
    rest = _GREETING_PREFIX.sub("", t, count=1).strip(" ,")
    if rest != t and rest and _HOW_ARE_YOU.match(rest):
        return SocialIntent("greeting_how_are_you", tod)

    for candidate in (t, _strip_fillers(t)):
        if not candidate:
            # Only fillers left, e.g. "hey boss": a greeting if it contained a greeting word.
            if re.search(r"\b(?:hey|hi|hello)\b", t):
                return SocialIntent("greeting", tod)
            break
        if _GREETING.match(candidate):
            return SocialIntent("greeting", tod)
        if _HOW_ARE_YOU.match(candidate):
            return SocialIntent("how_are_you")
        if _FAREWELL.match(candidate):
            return SocialIntent("farewell", tod)
        if _THANKS.match(candidate):
            return SocialIntent("thanks")
        if _COMPLIMENT.match(candidate):
            return SocialIntent("compliment")
    if _ACK.match(t):
        return SocialIntent("acknowledgement")
    return None


def current_time_of_day(now: datetime | None = None) -> str:
    h = (now or datetime.now()).hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "evening"
    return "night"


_REPLIES: dict[str, tuple[str, ...]] = {
    "greeting": (
        "Hello, Boss! How can I help you today?",
        "Hi, Boss! It's lovely to hear from you. What can I help you with?",
        "Hey, Boss! What can I do for you?",
        "Hello again, Boss. What would you like to do?",
    ),
    "greeting_morning": (
        "Good morning, Boss! I hope you're having a wonderful day. How may I help you?",
        "Good morning, Boss! Ready when you are. What's first today?",
    ),
    "greeting_afternoon": (
        "Good afternoon, Boss! How can I help you this afternoon?",
        "Good afternoon, Boss! What can I do for you?",
    ),
    "greeting_evening": (
        "Good evening, Boss! How can I assist you this evening?",
        "Good evening, Boss! I hope your day went well. What can I do for you?",
    ),
    "greeting_how_are_you": (
        "Hello, Boss! I'm doing well, thank you for asking. How are you doing?",
        "Hi, Boss! I'm doing great, thanks. How about you?",
    ),
    "how_are_you": (
        "I'm doing well, Boss. Thank you for asking! How are you doing?",
        "I'm doing great, thanks for asking. How has your day been?",
        "All good on my side, Boss. How are you feeling today?",
    ),
    "farewell": (
        "See you soon, Boss. Take care, and I'll be here whenever you need me.",
        "Goodbye for now, Boss. Take care!",
        "See you later, Boss. I'll be right here whenever you need me.",
    ),
    "farewell_night": (
        "Good night, Boss. Sleep well, and I'll be here whenever you need me.",
        "Good night, Boss. Rest well!",
    ),
    "thanks": (
        "You're very welcome, Boss!",
        "Happy to help, Boss.",
        "Anytime, Boss. Let me know if there's anything else.",
        "My pleasure!",
    ),
    "compliment": (
        "That's so kind of you, Boss. Thank you!",
        "Aw, thank you, Boss. That really means a lot.",
        "Thank you, Boss! I'm always happy to help you.",
    ),
    "acknowledgement": (
        "Alright, Boss. Just let me know if you need anything else.",
        "Sounds good.",
        "Okay! I'm here if you need me.",
    ),
}


class SocialResponder:
    """Picks natural replies and rotates wording so the same template isn't repeated."""

    def __init__(self) -> None:
        self._cycles: dict[str, itertools.cycle] = {k: itertools.cycle(v) for k, v in _REPLIES.items()}

    def reply(self, intent: SocialIntent, now: datetime | None = None) -> str:
        key = intent.kind
        if key == "greeting" and intent.time_of_day in ("morning", "afternoon", "evening"):
            key = f"greeting_{intent.time_of_day}"
        elif key == "farewell" and intent.time_of_day == "night":
            key = "farewell_night"
        elif key == "farewell" and current_time_of_day(now) == "night":
            key = "farewell_night"
        return next(self._cycles[key])
