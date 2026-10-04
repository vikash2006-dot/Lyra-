"""Unit tests for LYRA personality profiles."""

from lyra.companion.personality import DEFAULT_TRAITS, PersonalityProfile


def test_personality_default_traits() -> None:
    """Verify default traits match requirements."""
    profile = PersonalityProfile()
    assert profile.name == "LYRA"
    assert "helpful" in profile.traits
    assert "friendly" in profile.traits
    assert "intelligent" in profile.traits
    assert "calm" in profile.traits
    assert "honest" in profile.traits
    assert "concise" in profile.traits
    assert "context-aware" in profile.traits


def test_personality_build_system_prompt() -> None:
    """Verify system prompt contains persona guidance and guidelines."""
    profile = PersonalityProfile()
    prompt = profile.build_system_prompt()

    assert "You are LYRA" in prompt
    assert "helpful, concise, and direct" in prompt
    assert "calm, polite, and intelligent" in prompt
    assert "safety always take precedence" in prompt


def test_personality_custom_instructions() -> None:
    """Verify custom instructions are appended to system prompt."""
    profile = PersonalityProfile(custom_instructions="Always answer with metric units.")
    prompt = profile.build_system_prompt()

    assert "Always answer with metric units." in prompt
    assert "You are LYRA" in prompt
