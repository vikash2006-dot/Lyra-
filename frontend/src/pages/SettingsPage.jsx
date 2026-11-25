import { useState } from "react";
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
  const [testing, setTesting] = useState(false);
  const s = settings.data;

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
      const audio = await speak("Hi, I'm LYRA. This is how I sound.", prefs.voice || null);
      playBase64Audio(audio.audio_base64, audio.mime_type, { onEnd: () => setTesting(false) });
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
          <Toggle label="Speak replies" description="Play LYRA's spoken response after voice commands." checked={prefs.autoSpeak} onChange={(v) => setPrefs({ autoSpeak: v })} />
          <Toggle label="Hands-free conversation" description="Start listening again automatically after LYRA finishes speaking." checked={prefs.handsFree} onChange={(v) => setPrefs({ handsFree: v })} />
          <div className="field-row">
            <label htmlFor="voice-select">Voice</label>
            <select id="voice-select" value={prefs.voice} onChange={(e) => setPrefs({ voice: e.target.value })}>
              <option value="">System default</option>
              {(voices.data || []).map((v, i) => <option key={`${v.name}-${v.locale}-${i}`} value={v.name}>{v.name} ({v.locale})</option>)}
            </select>
            <button className="btn btn-ghost btn-sm" onClick={testVoice} disabled={testing}>{testing ? "Playing…" : "Test voice"}</button>
          </div>
          {vstatus.data && (
            <p className="muted small">
              Speech recognition: {vstatus.data.stt_provider} {vstatus.data.stt_ready ? "(ready)" : "(unavailable)"} ·
              Speech synthesis: {vstatus.data.tts_provider} {vstatus.data.tts_ready ? "(ready)" : "(unavailable)"}
            </p>
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
