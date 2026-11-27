"""Greeting/farewell intents, emotional cues, reply styling and voice identity."""

from datetime import datetime
import io
import math
import random
import struct
import wave

import pytest

from lyra.companion.emotion import EmotionAnalyzer, build_turn_guidance
from lyra.companion.personality import PersonalityProfile, ReplyStyler
from lyra.companion.social import SocialResponder, detect_social_intent
from lyra.voice.audio_events import detect_coughs
from lyra.voice.voices import prepare_speech_text, select_female_voice, split_for_speech


@pytest.mark.parametrize("text,kind,tod", [
    ("Hello, Lyra.", "greeting", None),
    ("Hi Lyra", "greeting", None),
    ("hey boss", "greeting", None),
    ("Good morning, Lyra.", "greeting", "morning"),
    ("Good evening Lyra", "greeting", "evening"),
    ("How are you, Lyra?", "how_are_you", None),
    ("Hi Lyra, how are you?", "greeting_how_are_you", None),
    ("Bye", "farewell", None),
    ("Goodbye Lyra", "farewell", None),
    ("See you later", "farewell", None),
    ("I'm leaving now", "farewell", None),
    ("Good night Lyra", "farewell", "night"),
    ("Thanks a lot!", "thanks", None),
    ("You're amazing", "compliment", None),
])
def test_social_intents(text, kind, tod):
    intent = detect_social_intent(text)
    assert intent is not None and intent.kind == kind and intent.time_of_day == tod


@pytest.mark.parametrize("text", [
    "Hi Lyra, open YouTube",
    "Hello, how does DNS work?",
    "Create a folder named Projects on my Desktop",
    "good morning routine ideas for students please and explain them",
])
def test_tasks_and_questions_are_not_social(text):
    assert detect_social_intent(text) is None


def test_greetings_never_get_farewell_replies():
    responder = SocialResponder()
    for _ in range(8):
        reply = responder.reply(detect_social_intent("Hello Lyra"))
        assert "see you" not in reply.lower() and "bye" not in reply.lower()
        assert "help" in reply.lower() or "do for you" in reply.lower() or "like to do" in reply.lower()
    assert responder.reply(detect_social_intent("Good morning Lyra")).startswith("Good morning, Boss!")
    farewell = responder.reply(detect_social_intent("bye"), now=datetime(2026, 1, 1, 15, 0))
    assert "see you" in farewell.lower() or "goodbye" in farewell.lower()


def test_social_replies_vary():
    responder = SocialResponder()
    intent = detect_social_intent("thanks")
    assert len({responder.reply(intent) for _ in range(4)}) > 1


@pytest.mark.parametrize("text,emotion", [
    ("I'm feeling really low today", "sadness"),
    ("Today was a terrible day", "sadness"),
    ("I finally completed my project!", "excitement"),
    ("I'm so excited about my internship!", "excitement"),
    ("I'm exhausted", "tiredness"),
    ("I'm angry because this code isn't working", "anger"),
    ("this still isn't working, ugh", "frustration"),
    ("I've been coughing all day and feel unwell", "unwell"),
])
def test_emotion_cues(text, emotion):
    signal = EmotionAnalyzer().analyze(text)
    assert signal is not None and signal.emotion == emotion


@pytest.mark.parametrize("text", [
    "What is the difference between TCP and UDP?",
    "Open YouTube and search for music",
    "Explain how a Python decorator works",
])
def test_no_emotion_for_neutral_requests(text):
    assert EmotionAnalyzer().analyze(text) is None


def test_guidance_is_hedged_and_non_diagnostic():
    g = build_turn_guidance(EmotionAnalyzer().analyze("I'm feeling really low today"))
    assert "not certain" in g
    cough = build_turn_guidance(None, [{"type": "cough", "confidence": 0.9}])
    assert "Do not diagnose" in cough and "uncertain" in cough
    assert build_turn_guidance(None, None) is None


def test_system_prompt_has_identity_and_greeting_rules():
    prompt = PersonalityProfile().build_system_prompt()
    assert "female" in prompt and "Boss" in prompt
    assert "Farewell phrases" in prompt and "never diagnose" in prompt


def test_reply_styler():
    styler = ReplyStyler()
    assert styler.success("Done, I created Projects on your Desktop.").endswith("I created Projects on your Desktop.")
    assert styler.success("Done. Set volume to 80%.").endswith("Set volume to 80%.")
    fail = styler.failure("Permission denied")
    assert fail.startswith("I'm sorry, Boss") and "permission denied" in fail and "try again" in fail
    assert "i'll open notes for you" in styler.acknowledgement("Open Notes").lower()


def test_female_voice_selection_prefers_natural_voices():
    voices = (
        {"name": "Rishi (English (India))", "locale": "en_IN"},
        {"name": "Kathy", "locale": "en_US"},
        {"name": "Samantha", "locale": "en_US"},
        {"name": "Ava (Premium)", "locale": "en_US"},
        {"name": "Daniel", "locale": "en_GB"},
    )
    assert select_female_voice(voices=voices) == "Ava (Premium)"
    assert select_female_voice(voices=voices[:3]) == "Samantha"
    assert select_female_voice("Kathy", voices=voices) == "Kathy"  # explicit, installed choice wins
    assert select_female_voice(voices=({"name": "Daniel", "locale": "en_GB"},)) is None


def test_speech_text_is_clean_and_chunked():
    assert prepare_speech_text("**Sure!** Steps:\n- Open `Finder`\n- Visit [docs](https://a.b) 😊") == \
        "Sure! Steps: Open Finder. Visit docs."
    chunks = split_for_speech("Hi. " + "This is a fairly long sentence for testing. " * 10)
    assert chunks[0] and len(chunks) >= 2 and all(len(c) <= 260 for c in chunks)


def _wav(samples, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, x)) * 32767)) for x in samples))
    return buf.getvalue()


def _clip(parts):
    random.seed(3)
    out = []
    for kind, dur in parts:
        n = int(dur * 16000)
        if kind == "silence":
            out += [random.gauss(0, 0.002) for _ in range(n)]
        elif kind == "cough":
            out += [0.6 * min(1, i / 192) * math.exp(-i / 1120) * random.gauss(0, 1) / 2 for i in range(n)]
        else:  # voiced, speech-like
            out += [0.3 * math.sin(math.pi * i / n) * sum(math.sin(2 * math.pi * f * i / 16000) / (k + 1)
                    for k, f in enumerate((140, 280, 420, 700))) for i in range(n)]
    return _wav(out)


def test_cough_detection():
    events = detect_coughs(_clip([("silence", 0.5), ("cough", 0.3), ("silence", 0.5)]))
    assert len(events) == 1 and events[0].type == "cough" and events[0].confidence >= 0.7
    assert detect_coughs(_clip([("silence", 0.3), ("voice", 0.6), ("silence", 0.1), ("voice", 0.6)])) == []
    assert detect_coughs(_clip([("silence", 1.0)])) == []
    assert detect_coughs(b"not a wav") == []
