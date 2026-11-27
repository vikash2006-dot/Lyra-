"""Lightweight emotional-cue detection for more human, context-aware replies.

Detects *possible* emotional or situational signals from the user's words (and, when the
voice pipeline supplies them, audio events such as a cough). Results are hints for the AI,
never facts: they are phrased as "may be" with a confidence, and nothing here diagnoses
anything. Technical or task requests without emotional language yield no signal, so the
layer never gets in the way of normal work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


@dataclass(frozen=True)
class EmotionSignal:
    emotion: str
    confidence: float
    cues: tuple[str, ...] = field(default_factory=tuple)

    @property
    def level(self) -> str:
        return "high" if self.confidence >= 0.75 else "medium" if self.confidence >= 0.5 else "low"


# (emotion, weight, pattern). Patterns are matched on lower-cased text with word boundaries.
_LEXICON: tuple[tuple[str, float, str], ...] = (
    ("distress", 0.95, r"(?:want to die|kill myself|end it all|can'?t go on|no reason to live|hurt myself|self[- ]harm)"),
    ("distress", 0.7, r"(?:panic(?:king)?|can'?t breathe|scared|terrified|so afraid|breaking down|falling apart)"),
    ("sadness", 0.85, r"(?:feel(?:ing)? (?:really |so |very )?(?:low|down|sad|depressed|lonely|empty|hopeless|miserable))"),
    ("sadness", 0.7, r"(?:terrible|awful|horrible|worst|bad) day|heartbroken|broke up|lost my|passed away|i'?m (?:so )?sad|crying|miss (?:him|her|them)"),
    ("anger", 0.8, r"(?:i'?m|i am|so|really) (?:angry|furious|pissed|mad)|hate this|so annoying|fed up|sick of"),
    ("frustration", 0.75, r"(?:isn'?t|is not|not|doesn'?t|does not|won'?t|still not|never) work(?:ing|s)?|frustrat\w*|(?:keeps?|kept) (?:failing|crashing|breaking)|nothing works|stuck (?:on|with)|ugh+|argh+"),
    ("frustration", 0.7, r"(?:you (?:didn'?t|did not|don'?t|never) (?:listen|understand|do it)|that'?s (?:wrong|not what i (?:asked|said|meant))|you (?:got it|did it) wrong)"),
    ("stress", 0.75, r"(?:stress(?:ed|ful)?|overwhelm\w*|anxious|anxiety|under (?:a lot of )?pressure|deadline|too much (?:work|to do)|worried)"),
    ("tiredness", 0.8, r"(?:exhausted|so tired|really tired|very tired|i'?m tired|sleepy|drained|burn(?:ed|t) out|worn out|no energy)"),
    ("unwell", 0.75, r"(?:i'?m|i am|feel(?:ing)?) (?:sick|ill|unwell|not (?:feeling )?(?:well|good|great))|(?:have|got) (?:a |the )?(?:cold|fever|flu|headache|sore throat|cough)|coughing|sneez\w*"),
    ("confusion", 0.6, r"(?:i'?m (?:so )?confused|don'?t understand|doesn'?t make sense|what do you mean|lost here|makes no sense)"),
    ("excitement", 0.85, r"(?:so excited|can'?t wait|finally (?:did|got|finished|completed|passed)|i (?:got|landed) (?:the|a|my) (?:job|internship|offer)|got (?:selected|accepted|promoted)|we won|i passed|nailed it|yay+|woo+hoo|omg)"),
    ("happiness", 0.65, r"(?:i'?m (?:so |really )?(?:happy|glad|thrilled|delighted)|great day|feeling (?:great|good|awesome|amazing)|best day)"),
    ("calm", 0.4, r"(?:relaxed|chilling|peaceful|calm day|taking it easy)"),
)

_TECH_HINT = re.compile(
    r"\b(?:how (?:do|does|to|can)|what is|what are|explain|define|difference between|syntax|example of|write (?:a|the) "
    r"(?:code|function|script)|convert|calculate)\b",
    re.IGNORECASE,
)

_GUIDANCE: dict[str, str] = {
    "distress": (
        "The user may be in real distress. Respond with warmth and calm, take them seriously, and gently "
        "encourage reaching out to someone they trust or local emergency/crisis services if they could be in "
        "danger. Do not lecture."
    ),
    "sadness": (
        "The user may be feeling sad or low. Acknowledge it kindly in one sentence (e.g. you're sorry they feel "
        "this way) and gently offer to listen. Do not jump to offering tasks."
    ),
    "anger": (
        "The user may be angry. Stay calm and kind, don't argue or get defensive, briefly acknowledge it, then help."
    ),
    "frustration": (
        "The user may be frustrated (possibly with code or with LYRA). Briefly acknowledge it without being "
        "defensive or lecturing, then focus on concretely solving the problem."
    ),
    "stress": (
        "The user may be stressed. Be reassuring and practical; offer to help break things down into small steps."
    ),
    "tiredness": (
        "The user may be tired. Keep the reply short and gentle; you may offer to keep things simple or suggest a "
        "short break."
    ),
    "unwell": (
        "The user may not be feeling well. Respond with gentle care (ask if they're okay / suggest rest or water "
        "if natural). Never diagnose or give medical conclusions; suggest a doctor only if they describe "
        "something serious."
    ),
    "confusion": "The user may be confused. Explain more simply and clearly, and check if it makes sense.",
    "excitement": "The user sounds excited. Share their enthusiasm warmly and congratulate them if appropriate.",
    "happiness": "The user sounds happy. Match their positive energy naturally.",
    "calm": "",
}


class EmotionAnalyzer:
    def __init__(self, min_confidence: float = 0.5) -> None:
        self.min_confidence = min_confidence
        self._compiled = [(e, w, re.compile(rf"\b(?:{p})", re.IGNORECASE)) for e, w, p in _LEXICON]

    def analyze(self, text: str) -> EmotionSignal | None:
        lowered = (text or "").lower()
        if not lowered.strip():
            return None
        scores: dict[str, float] = {}
        cues: dict[str, list[str]] = {}
        for emotion, weight, rx in self._compiled:
            m = rx.search(lowered)
            if m:
                # Combine multiple cues for the same emotion without exceeding 0.97.
                prev = scores.get(emotion, 0.0)
                scores[emotion] = min(0.97, prev + weight * (1 - prev))
                cues.setdefault(emotion, []).append(m.group(0))
        if not scores:
            return None
        if "!" in text and any(e in scores for e in ("excitement", "happiness", "anger")):
            for e in ("excitement", "happiness", "anger"):
                if e in scores:
                    scores[e] = min(0.97, scores[e] + 0.05)
        emotion = max(scores, key=lambda e: (e == "distress", scores[e]))
        conf = scores[emotion]
        # Pure technical questions only count if the emotional cue is strong.
        if _TECH_HINT.search(lowered) and conf < 0.75:
            return None
        if conf < self.min_confidence:
            return None
        return EmotionSignal(emotion, round(conf, 2), tuple(cues[emotion]))


def build_turn_guidance(
    signal: EmotionSignal | None,
    audio_events: list[dict[str, Any]] | None = None,
    is_task: bool = False,
) -> str | None:
    """Short system-prompt addendum for this turn, or None when nothing is noteworthy."""
    lines: list[str] = []
    if signal and _GUIDANCE.get(signal.emotion):
        lines.append(
            f"Possible emotional cue (not certain, confidence {signal.level}): {signal.emotion}. "
            f"{_GUIDANCE[signal.emotion]}"
        )
    for ev in audio_events or []:
        if ev.get("type") == "cough":
            lines.append(
                "Audio analysis suggests the user may have coughed while speaking (this is an uncertain signal). "
                "Answer their request, and add one short, gentle line checking they're okay. Do not diagnose, do not "
                "assume they are ill, and do not repeat this check later in the conversation."
            )
    if not lines:
        return None
    if is_task:
        lines.append("They also asked for something specific: still do it fully; keep any emotional acknowledgement to one short sentence.")
    return "Guidance for this reply only:\n- " + "\n- ".join(lines)
