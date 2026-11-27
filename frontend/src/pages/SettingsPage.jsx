import { useEffect, useState } from "react";
import Header from "../components/layout/Header";
import { useLayout } from "../components/layout/Layout";
import { Badge, Card, ErrorBanner, PageHeader, Spinner, StatusDot, Toggle } from "../components/common/ui";
import { API_TOKEN, API_URL } from "../config";
import { useApp } from "../context/AppContext";
import { useChat } from "../context/ChatContext";
import { useAsync } from "../hooks/useAsync";
import { usePreferences } from "../hooks/usePreferences";
import { getProviders, getSettings, updateSettings } from "../services/settingsApi";
import { listVoices, speak, voiceStatus } from "../services/voiceApi";
import { playBase64Audio } from "../utils/audio";
import { titleCase } from "../utils/formatters";

export default function SettingsPage() {
  const { openMenu } = useLayout();
  const { notify, health, eventsStatus, refreshHealth } = useApp();
  const { socketStatus } = useChat();
  const [prefs, setPrefs] = usePreferences();
  const settings = useAsync(getSettings, []);
  const providers = useAsync(getProviders, []);
  const voices = useAsync(listVoices, []);
  const vstatus = useAsync(voiceStatus, []);
  const [saving, setSaving] = useState(false);
  const [savingPref, setSavingPref] = useState(false);
  const [testing, setTesting] = useState(false);
  const [rate, setRate] = useState(null);
  const s = settings.data;
  const femaleVoices = (voices.data || []).filter((v) => v.female);

  useEffect(() => {
    if (s?.assistant?.speech_rate) setRate(s.assistant.speech_rate);
  }, [s?.assistant?.speech_rate]);

  const saveAssistant = async (changes) => {
    if (changes.speech_rate != null && changes.speech_rate === s?.assistant.speech_rate) return;
    setSavingPref(true);
    try {
      settings.setData(await updateSettings(changes));
      vstatus.reload();
    } catch (err) {
      notify(err.message, "error");
    } finally {
      setSavingPref(false);
    }
  };

  const setOffline = async (value) => {
    setSaving(true);
    try {
      settings.setData(await updateSettings({ offline_mode: value }));
      providers.reload();
      refreshHealth();
      notify(value ? "Offline mode on: only local AI is used." : "Offline mode off.", "success");
    } catch (err) {
      notify(err.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const testVoice = async () => {
    setTesting(true);
    try {
      const audio = await speak("Hello, Boss! I'm LYRA. This is how I sound. How can I help you today?");
      playBase64Audio(audio.audio_base64, audio.mime_type, { volume: prefs.volume, onEnd: () => setTesting(false) });
    } catch (err) {
      notify(err.message, "error");
      setTesting(false);
    }
  };

  return (
    <div className="page">
      <Header title="Settings" onMenu={openMenu} />
      <div className="page-body narrow">
        <PageHeader title="Settings" subtitle="Preferences, voice, AI providers and connection status." />
        <ErrorBanner error={settings.error} onRetry={settings.reload} />

        <Card title="General" icon="settings">
          {!s ? <Spinner /> : (
            <Toggle
              label="Offline mode"
              description="Use only the local AI runtime (Ollama) and block tools that need the internet."
              checked={s.general.offline_mode}
              onChange={setOffline}
              disabled={saving}
            />
          )}
          <Toggle
            label="Show task activity panel"
            description="Live progress of actions LYRA performs on your computer."
            checked={prefs.showActivity}
            onChange={(v) => setPrefs({ showActivity: v })}
          />
        </Card>

        <Card title="Voice" icon="volume">
          <div className="field-row">
            <label htmlFor="voice-select">LYRA's voice</label>
            <select
              id="voice-select"
              value={s?.assistant.voice || ""}
              onChange={(e) => saveAssistant({ voice: e.target.value })}
              disabled={!s || savingPref}
            >
              {femaleVoices.length > 0 && (
                <optgroup label="Female voices">
                  {femaleVoices.map((v, i) => (
                    <option key={`${v.name}-${i}`} value={v.name}>
                      {v.name}{v.recommended ? " — recommended" : ""} ({v.locale})
                    </option>
                  ))}
                </optgroup>
              )}
              {s?.assistant.voice && !femaleVoices.some((v) => v.name === s.assistant.voice) && (
                <option value={s.assistant.voice}>{s.assistant.voice}</option>
              )}
            </select>
            <button className="btn btn-ghost btn-sm" onClick={testVoice} disabled={testing}>{testing ? "Playing…" : "Test voice"}</button>
          </div>
          <div className="field-row">
            <label htmlFor="rate">Speaking speed</label>
            <input
              id="rate"
              type="range"
              min="140"
              max="230"
              step="5"
              value={rate ?? 182}
              onChange={(e) => setRate(Number(e.target.value))}
              onMouseUp={() => saveAssistant({ speech_rate: rate })}
              onKeyUp={() => saveAssistant({ speech_rate: rate })}
              onTouchEnd={() => saveAssistant({ speech_rate: rate })}
              disabled={!s}
            />
            <span className="range-value">{rate ?? "—"} wpm</span>
          </div>
          <div className="field-row">
            <label htmlFor="volume">Volume</label>
            <input id="volume" type="range" min="0" max="1" step="0.05" value={prefs.volume}
              onChange={(e) => setPrefs({ volume: Number(e.target.value) })} />
            <span className="range-value">{Math.round(prefs.volume * 100)}%</span>
          </div>
          <Toggle label="Speak replies" description="Play LYRA's spoken response after voice commands." checked={prefs.autoSpeak} onChange={(v) => setPrefs({ autoSpeak: v })} />
          <Toggle label="Allow interrupting" description="Tap the mic while LYRA is working or speaking to stop her." checked={prefs.allowInterrupt} onChange={(v) => setPrefs({ allowInterrupt: v })} />
          <Toggle label="Hands-free conversation" description="Start listening again automatically after LYRA finishes speaking." checked={prefs.handsFree} onChange={(v) => setPrefs({ handsFree: v })} />
          <p className="muted small">
            For an even more natural voice, download “Ava (Premium)” or “Zoe (Premium)” in macOS System Settings → Accessibility →
            Spoken Content → System Voice → Manage Voices; LYRA picks it up automatically after a backend restart.
          </p>
        </Card>

        <Card title="Assistant behaviour" icon="sparkle">
          {!s ? <Spinner /> : (
            <>
              <Toggle
                label="Emotional awareness"
                description="Notice possible emotional cues (sad, stressed, excited…) and respond with care. Never used for technical questions."
                checked={s.assistant.emotional_awareness}
                onChange={(v) => saveAssistant({ emotional_awareness: v })}
                disabled={savingPref}
              />
              <Toggle
                label="Screen awareness"
                description="Let LYRA look at your screen when you ask (\u201clook at my screen\u201d, \u201cclick the Login button\u201d). More controls on the Screen page."
                checked={s.assistant.screen_awareness}
                onChange={(v) => saveAssistant({ screen_awareness: v })}
                disabled={savingPref}
              />
              <Toggle
                label="Use cloud vision AI for screenshots"
                description="Allows sending screenshots to your AI vision provider. Off = on-device text recognition only."
                checked={s.assistant.vision_cloud_consent}
                onChange={(v) => saveAssistant({ vision_cloud_consent: v })}
                disabled={savingPref || !s.assistant.screen_awareness}
              />
              <Toggle
                label="Audio event detection"
                description="Analyse the sound of voice clips for non-speech events, on this computer only."
                checked={s.assistant.audio_event_detection}
                onChange={(v) => saveAssistant({ audio_event_detection: v })}
                disabled={savingPref}
              />
              <Toggle
                label="Cough detection"
                description="If a cough is detected, LYRA gently checks you're okay — at most once every 10 minutes. It never diagnoses."
                checked={s.assistant.cough_detection}
                onChange={(v) => saveAssistant({ cough_detection: v })}
                disabled={savingPref || !s.assistant.audio_event_detection}
              />
            </>
          )}
        </Card>

        <Card title="AI providers" icon="sparkle" actions={<button className="btn btn-ghost btn-sm" onClick={providers.reload}>Refresh</button>}>
          {!providers.data ? <Spinner /> : (
            <>
              <p className="muted small">Fallback order follows the backend's PROVIDER_PRIORITY. Currently using <strong>{providers.data.current_provider}</strong>.</p>
              <table className="table">
                <thead><tr><th>#</th><th>Provider</th><th>Model</th><th>Status</th></tr></thead>
                <tbody>
                  {providers.data.providers.map((p) => (
                    <tr key={p.name}>
                      <td>{p.priority ?? "–"}</td>
                      <td>{p.display_name}</td>
                      <td className="muted">{p.model || "–"}</td>
                      <td><Badge tone={p.status === "AVAILABLE" ? "good" : p.configured ? "warn" : "neutral"}>{titleCase(p.status.toLowerCase())}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted small">API keys live only in <code>backend/.env</code> and are never sent to this app.</p>
            </>
          )}
        </Card>

        <Card title="Connection" icon="server">
          <dl className="kv">
            <dt>Backend URL</dt><dd><code>{API_URL}</code></dd>
            <dt>Health</dt><dd><StatusDot state={health.state} /> {titleCase(health.state)}</dd>
            <dt>Chat stream</dt><dd>{titleCase(socketStatus)}</dd>
            <dt>Event stream</dt><dd>{titleCase(eventsStatus)}</dd>
            <dt>Access token</dt><dd>{API_TOKEN ? "Configured" : s?.server.token_required ? "Required but missing" : "Not required (local only)"}</dd>
          </dl>
        </Card>

        {s && (
          <Card title="Backend configuration" icon="file">
            <p className="muted small">{s.note}</p>
            <dl className="kv">
              <dt>Environment</dt><dd>{s.general.environment}</dd>
              <dt>Speech providers</dt><dd>STT: {s.voice.stt_provider} · TTS: {s.voice.tts_provider}</dd>
              <dt>App confirmation</dt><dd>{s.computer.require_confirmation ? "Required for risky actions" : "Off"}</dd>
              <dt>Allowed apps</dt><dd>{s.computer.allowed_apps.join(", ")}</dd>
              <dt>Blocked apps</dt><dd>{s.computer.blocked_apps.join(", ")}</dd>
              <dt>Browser</dt><dd>{s.browser.driver} · {s.browser.headless ? "headless" : "visible"}</dd>
              <dt>Anakin</dt><dd>{s.integrations.anakin_configured ? `Configured · ${s.integrations.anakin_workflows} workflows` : "Not configured"}</dd>
              <dt>Web search</dt><dd>{s.integrations.tavily_configured ? "Tavily" : "DuckDuckGo (no key)"}</dd>
              <dt>Upload limit</dt><dd>{s.server.max_upload_mb} MB</dd>
            </dl>
          </Card>
        )}
      </div>
    </div>
  );
}
