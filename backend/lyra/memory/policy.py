"""Memory storage policies enforcing privacy, relevance, and sensitivity filtering."""

import re

from lyra.models.memory import MemoryType

SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # API keys, tokens, and secret prefixes
    re.compile(r"(?i)\b(?:sk|ghp|tvly|gsk|glpat|xox[baprs])-[a-zA-Z0-9_\-]{16,}\b"),
    re.compile(r"(?i)\bbearer\s+[a-zA-Z0-9_\-\.]{20,}\b"),
    # Passwords or credentials
    re.compile(r"(?i)\b(?:password|passwd|secret_key|api_key|private_key)\s*(?:[:=]|\bis\b)\s*\S+"),
    # Social Security Numbers (US format)
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # Credit card numbers (13-19 contiguous or formatted digits)
    re.compile(r"\b(?:\d{4}[ -]?){3}\d{1,4}\b"),
    # Private crypto keys / seed phrases
    re.compile(r"(?i)\b(?:seed\s+phrase|private\s+key)\s*(?:[:=]|\bis\b)\s*\S+"),
)

TRIVIAL_PHRASES: frozenset[str] = frozenset({
    "ok",
    "okay",
    "yes",
    "no",
    "yeah",
    "nope",
    "hello",
    "hi",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
    "good night",
    "thanks",
    "thank you",
    "thanks a lot",
    "bye",
    "goodbye",
    "cool",
    "got it",
    "sure",
    "alright",
    "fine",
    "see you",
})


class MemoryPolicy:
    """Evaluates memory candidates to ensure privacy compliance and selective retention."""

    def __init__(
        self,
        min_importance: float = 0.2,
        min_confidence: float = 0.3,
        allow_sensitive: bool = False,
    ) -> None:
        self.min_importance = min_importance
        self.min_confidence = min_confidence
        self.allow_sensitive = allow_sensitive

    def contains_sensitive_data(self, text: str) -> bool:
        """Check if text matches any sensitive information pattern (PII, credentials)."""
        if not text:
            return False
        return any(pattern.search(text) is not None for pattern in SENSITIVE_PATTERNS)

    def is_trivial_content(self, text: str) -> bool:
        """Check if candidate content is ephemeral or meaningless conversational chatter."""
        clean = text.strip().lower().rstrip(".!?,")
        if len(clean) < 3:
            return True
        return clean in TRIVIAL_PHRASES

    def evaluate_candidate(
        self,
        user_id: str,
        content: str,
        memory_type: MemoryType,
        importance: float = 0.5,
        confidence: float = 0.9,
    ) -> tuple[bool, str | None]:
        """Evaluate whether a memory candidate is permitted to be stored.

        Returns:
            Tuple of (is_allowed: bool, rejection_reason: str | None).
        """
        if not user_id or not user_id.strip():
            return False, "User ID cannot be empty."

        clean_content = content.strip()
        if not clean_content:
            return False, "Memory content cannot be empty."

        # 1. Privacy & Sensitivity check
        if not self.allow_sensitive and self.contains_sensitive_data(clean_content):
            return False, "Content contains sensitive credentials or personal financial/identity data."

        # 2. Ephemeral / Trivial chatter filter (Do not store everything)
        if self.is_trivial_content(clean_content):
            return False, "Content is trivial conversational chatter."

        # 3. Minimum Importance threshold
        if importance < self.min_importance:
            return (
                False,
                f"Memory importance ({importance:.2f}) is below minimum threshold ({self.min_importance:.2f}).",
            )

        # 4. Minimum Confidence threshold
        if confidence < self.min_confidence:
            return (
                False,
                f"Memory confidence ({confidence:.2f}) is below minimum threshold ({self.min_confidence:.2f}).",
            )

        # 5. Category check
        if not isinstance(memory_type, MemoryType):
            return False, f"Invalid memory type: {memory_type}."

        return True, None
