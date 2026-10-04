"""Unit tests for LYRA CLI entry point."""

import io
from unittest.mock import patch
import pytest

from lyra.interfaces.cli import main


@pytest.fixture(autouse=True)
def clean_cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure CLI unit tests execute in an isolated environment without external API keys."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("CEREBRAS_API_KEY", "")
    monkeypatch.setenv("LOCAL_PROVIDER_ENABLED", "false")


def test_cli_single_prompt_mode(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that CLI handles single-prompt arguments and exits with code 0."""
    monkeypatch.setenv("LYRA_ENV", "development")
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    exit_code = main(["Hello", "LYRA"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "LYRA starting..." in captured.out
    assert "Environment: development" in captured.out
    assert "LYRA is ready." in captured.out
    assert "You: Hello LYRA" in captured.out
    assert "LYRA:" in captured.out


def test_cli_interactive_exit_command(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that CLI interactive loop exits cleanly when user types 'exit'."""
    monkeypatch.setenv("LYRA_ENV", "development")
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    # Simulate user typing "exit"
    with patch("builtins.input", return_value="exit"):
        exit_code = main([])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "LYRA starting..." in captured.out
    assert "Goodbye!" in captured.out


def test_cli_interactive_conversation_and_eof(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that CLI interactive loop handles a user prompt followed by EOF (Ctrl+D)."""
    monkeypatch.setenv("LYRA_ENV", "development")
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    # Simulate one question, then EOF
    input_iterator = iter(["What can you do?", EOFError()])

    def mock_input(prompt: str) -> str:
        val = next(input_iterator)
        if isinstance(val, Exception):
            raise val
        return val

    with patch("builtins.input", side_effect=mock_input):
        exit_code = main([])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "LYRA:" in captured.out
    assert "Goodbye!" in captured.out


def test_cli_handles_configuration_error(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that CLI handles configuration errors gracefully with exit code 1."""
    monkeypatch.setenv("LOG_LEVEL", "INVALID_LOG_LEVEL")

    exit_code = main([])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "LYRA Configuration Error:" in captured.err


def test_cli_time_tool_invocation(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that CLI handles time query by invoking TimeTool and formatting response."""
    monkeypatch.setenv("LYRA_ENV", "development")
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    exit_code = main(["What", "time", "is", "it?"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "You: What time is it?" in captured.out
    assert "LYRA: The current time is" in captured.out


def test_cli_weather_tool_invocation(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify CLI executes WeatherTool when asked for weather."""
    import json
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("LYRA_ENV", "development")
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    geo_data = {"results": [{"name": "Tokyo", "latitude": 35.68, "longitude": 139.76, "country": "Japan"}]}
    forecast_data = {"current": {"temperature_2m": 22.0, "apparent_temperature": 21.5, "relative_humidity_2m": 55, "weather_code": 0, "wind_speed_10m": 8.0}}

    def mock_urlopen(req, timeout=10.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        raw = json.dumps(geo_data if "geocoding-api" in url else forecast_data).encode("utf-8")
        resp = MagicMock()
        resp.read.return_value = raw
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = None
        return resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        exit_code = main(["What", "is", "the", "weather", "in", "Tokyo?"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "The current weather in Tokyo, Japan is 22.0°C" in captured.out


def test_cli_search_tool_invocation(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify CLI executes SearchTool when asked to search."""
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("LYRA_ENV", "development")
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    html = """
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fpython.org">Python Home</a>
      <div class="result__snippet">Python programming language.</div>
    </div>
    """

    resp = MagicMock()
    resp.read.return_value = html.encode()
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=resp):
        exit_code = main(["search", "the", "web", "for", "Python"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Here is what I found for 'python':" in captured.out
    assert "Python Home" in captured.out


def test_cli_news_tool_invocation(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify CLI executes NewsTool when asked for news."""
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("LYRA_ENV", "development")
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    xml = """
    <rss version="2.0"><channel><item>
      <title>Space Probe Discovers Ice</title>
      <link>https://example.com/space</link>
      <description>Subsurface ice found on lunar crater.</description>
    </item></channel></rss>
    """

    resp = MagicMock()
    resp.read.return_value = xml.encode()
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=resp):
        exit_code = main(["What", "is", "the", "latest", "news?"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Latest Headlines" in captured.out
    assert "Space Probe Discovers Ice" in captured.out


def test_cli_maps_tool_invocation(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify CLI executes MapsTool when asked for directions or distance."""
    import json
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("LYRA_ENV", "development")
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    geo_paris = [{"lat": "48.85", "lon": "2.35", "display_name": "Paris, France"}]
    geo_lyon = [{"lat": "45.76", "lon": "4.83", "display_name": "Lyon, France"}]
    route = {"code": "Ok", "routes": [{"distance": 465000.0, "duration": 15000.0, "legs": [{"summary": "A 6"}]}]}

    def mock_urlopen(req, timeout=10.0):
        url = (req.full_url if hasattr(req, "full_url") else str(req)).lower()
        if "paris" in url:
            data = geo_paris
        elif "lyon" in url:
            data = geo_lyon
        else:
            data = route
        resp = MagicMock()
        resp.read.return_value = json.dumps(data).encode()
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = None
        return resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        exit_code = main(["How", "far", "is", "Paris", "from", "Lyon?"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Driving from Paris, France to Lyon, France is about 465.0 km" in captured.out


def test_cli_help_flags(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify that --help, -h, and help print the usage manual and return 0."""
    for flag in ("--help", "-h", "help"):
        exit_code = main([flag])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "LYRA — Modular Personal AI Operating System" in captured.out
        assert "lyra voice" in captured.out


def test_cli_voice_mode_dispatch(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that 'lyra voice' initializes and runs VoiceConversationManager."""
    monkeypatch.setenv("LYRA_ENV", "development")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("STT_PROVIDER", "mock")
    monkeypatch.setenv("TTS_PROVIDER", "mock")

    with patch("lyra.voice.conversation.VoiceConversationManager.run", return_value=None) as mock_run:
        exit_code = main(["voice"])

    assert exit_code == 0
    assert mock_run.called
    captured = capsys.readouterr()
    assert "Starting LYRA Voice Mode..." in captured.out


def test_cli_voice_mode_elevenlabs_dispatch(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that 'lyra voice' initializes properly with ElevenLabs TTS."""
    monkeypatch.setenv("LYRA_ENV", "development")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("STT_PROVIDER", "mock")
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-123")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "test-voice-id")

    with patch("lyra.voice.conversation.VoiceConversationManager.run", return_value=None) as mock_run:
        exit_code = main(["voice"])

    assert exit_code == 0
    assert mock_run.called
    captured = capsys.readouterr()
    assert "Starting LYRA Voice Mode..." in captured.out


