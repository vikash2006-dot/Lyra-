"""Unit tests for MemoryPolicy privacy and quality filtering."""

from lyra.memory.policy import MemoryPolicy
from lyra.models.memory import MemoryType


def test_memory_policy_allows_valid_candidate():
    policy = MemoryPolicy(min_importance=0.2, min_confidence=0.3)
    allowed, reason = policy.evaluate_candidate(
        user_id="alice",
        content="I prefer tea over coffee.",
        memory_type=MemoryType.PREFERENCE,
        importance=0.7,
        confidence=0.9,
    )
    assert allowed is True
    assert reason is None


def test_memory_policy_rejects_empty_fields():
    policy = MemoryPolicy()
    allowed, reason = policy.evaluate_candidate(
        user_id="",
        content="Valid content",
        memory_type=MemoryType.FACT,
    )
    assert allowed is False
    assert "User ID" in reason

    allowed, reason = policy.evaluate_candidate(
        user_id="user1",
        content="   ",
        memory_type=MemoryType.FACT,
    )
    assert allowed is False
    assert "content" in reason


def test_memory_policy_rejects_sensitive_api_keys():
    policy = MemoryPolicy()
    sensitive_samples = [
        "My secret key is sk-1234567890abcdef12345678",
        "api_key: ghp_1234567890abcdef1234567890abcdef",
        "Here is my password: superSecretPassword123",
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.somerandomsignaturestring",
        "SSN is 123-45-6789",
        "Card: 4111-2222-3333-4444",
    ]
    for sample in sensitive_samples:
        assert policy.contains_sensitive_data(sample) is True
        allowed, reason = policy.evaluate_candidate(
            user_id="alice",
            content=sample,
            memory_type=MemoryType.FACT,
        )
        assert allowed is False
        assert "sensitive" in reason.lower()


def test_memory_policy_rejects_trivial_content():
    policy = MemoryPolicy()
    trivial_inputs = ["hello", "hi", "ok", "okay!", "thanks", "thanks a lot.", "bye", "sure"]
    for word in trivial_inputs:
        assert policy.is_trivial_content(word) is True
        allowed, reason = policy.evaluate_candidate(
            user_id="alice",
            content=word,
            memory_type=MemoryType.FACT,
        )
        assert allowed is False
        assert "trivial" in reason.lower()


def test_memory_policy_threshold_filtering():
    policy = MemoryPolicy(min_importance=0.4, min_confidence=0.5)

    allowed, reason = policy.evaluate_candidate(
        user_id="alice",
        content="I sometimes watch movies",
        memory_type=MemoryType.HABIT,
        importance=0.2,  # below 0.4
        confidence=0.8,
    )
    assert allowed is False
    assert "importance" in reason.lower()

    allowed, reason = policy.evaluate_candidate(
        user_id="alice",
        content="I think I might visit Paris",
        memory_type=MemoryType.GOAL,
        importance=0.5,
        confidence=0.3,  # below 0.5
    )
    assert allowed is False
    assert "confidence" in reason.lower()
