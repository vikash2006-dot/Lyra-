import { useEffect, useState } from "react";
import Markdown from "../components/chat/Markdown";
import Icon from "../components/common/Icon";
import Header from "../components/layout/Header";
import { useLayout } from "../components/layout/Layout";
import { Badge, Card, ErrorBanner, PageHeader, Spinner, StatusDot, Toggle } from "../components/common/ui";
import { useApp } from "../context/AppContext";
import { useChat } from "../context/ChatContext";
import { useAsync } from "../hooks/useAsync";
import {
  analyzeScreen,
  askScreen,
  captureScreen,
  clearVisionContext,
  getVisionContext,
  requestScreenPermission,
  startMonitoring,
  stopMonitoring,
  updateVisionSettings,
  visionStatus,
} from "../services/visionApi";
import { timeAgo, titleCase } from "../utils/formatters";

export const VISION_STATE_LABELS = {
  disabled: "Screen awareness off",
  idle: "Waiting for request",
  capturing: "Capturing screen…",
  analyzing: "Analyzing screen…",
  analyzed: "Screen analyzed",
  executing: "Executing visual action…",
  verifying: "Verifying action…",
  monitoring: "Monitoring enabled",
  permission_denied: "Permission denied",
  failed: "Failed",
};
const BUSY = new Set(["capturing", "analyzing", "executing", "verifying"]);
const TONE = { analyzed: "good", monitoring: "accent", permission_denied: "bad", failed: "bad", disabled: "neutral" };

export default function ScreenPage() {
  const { openMenu } = useLayout();
  const { notify, vision } = useApp();
  const { activeSessionId } = useChat();
  const status = useAsync(visionStatus, []);
  const [ctx, setCtx] = useState(null);
  const [preview, setPreview] = useState(null);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(null);
  const [answer, setAnswer] = useState(null);
  const s = status.data;
  const liveState = s?.enabled === false ? "disabled" : vision.state || s?.state || "idle";

  useEffect(() => {
    getVisionContext(activeSessionId).then((d) => {
      if (d.context) {
        setCtx(d.context);
        setPreview(d.preview);
      }
    }).catch(() => {});
  }, [activeSessionId]);

  // Context produced elsewhere (e.g. a voice "look at my screen") arrives over the event stream.
  useEffect(() => {
    if (vision.context) setCtx(vision.context);
  }, [vision.context]);

  const run = async (key, fn) => {
    setBusy(key);
    try {
      return await fn();
    } catch (err) {
      notify(err.message, "error");
      return null;
    } finally {
      setBusy(null);
      status.reload();
    }
  };

  const capture = () => run("capture", async () => {
    const d = await captureScreen(activeSessionId);
    setCtx(d.context);
    setPreview(d.preview);
    setAnswer(null);
  });
  const analyze = () => run("analyze", async () => {
    const d = await analyzeScreen(question.trim() || null, activeSessionId);
    setCtx(d.context);
    setPreview(d.preview);
    setAnswer(d.context.answer || null);
  });
  const command = () => run("ask", async () => {
    const d = await askScreen(question.trim(), activeSessionId);
    setAnswer(d.response);
    if (d.context) setCtx(d.context);
  });
  const setSetting = (changes) => run("settings", async () => {
    await updateVisionSettings(changes);
  });
  const toggleMonitor = () => run("monitor", async () => {
    if (s?.monitoring?.running) await stopMonitoring();
    else await startMonitoring(5);
  });
  const clear = () => run("clear", async () => {
    await clearVisionContext(activeSessionId);
    setCtx(null);
    setPreview(null);
    setAnswer(null);
    notify("Visual context cleared.", "success");
  });

  const permissionDenied = s && s.screen_permission !== "granted" && s.screen_permission !== "unknown";
  const working = BUSY.has(liveState) || Boolean(busy && busy !== "settings");
  const actionable = (ctx?.elements || []).filter((e) => e.actionable);

  return (
    <div className="page">
      <Header title="Screen" onMenu={openMenu} />
      <div className="page-body">
        <PageHeader
          title="Screen awareness"
          subtitle="LYRA looks at your screen only when you ask, or while you have monitoring switched on."
          actions={
            <span className={`vision-pill tone-${TONE[liveState] || "busy"}`}>
              {working ? <Spinner size={12} /> : <StatusDot state={liveState === "analyzed" || liveState === "monitoring" ? "online" : liveState === "idle" ? "connecting" : liveState === "disabled" ? "idle" : "offline"} />}
              {VISION_STATE_LABELS[liveState] || titleCase(liveState)}
            </span>
          }
        />
        <ErrorBanner error={status.error} onRetry={status.reload} />

        {permissionDenied && (
          <div className="notice notice-warn">
            <Icon name="lock" size={18} />
            <div>
              <strong>Screen Recording permission is off.</strong>
              <p>
                macOS blocks screenshots until you allow it: System Settings → Privacy &amp; Security → Screen &amp; System
                Audio Recording → enable the app that runs LYRA's backend, then restart the backend. LYRA never bypasses this.
              </p>
              <button className="btn btn-ghost btn-sm" onClick={() => run("perm", requestScreenPermission)}>Ask macOS for permission</button>
            </div>
          </div>
        )}

        <div className="grid">
          <Card title="Status" icon="monitor">
            {!s ? <Spinner /> : (
              <dl className="kv">
                <dt>Active app</dt><dd>{s.active_app || "—"}</dd>
                <dt>Window</dt><dd className="truncate">{s.active_window || (s.screen_permission === "granted" ? "—" : "Needs permission")}</dd>
                <dt>Screen capture</dt><dd><Badge tone={s.screen_permission === "granted" ? "good" : "bad"}>{titleCase(s.screen_permission)}</Badge></dd>
                <dt>UI elements</dt><dd><Badge tone={s.accessibility_permission ? "good" : "warn"}>{s.accessibility_permission ? "Accessibility on" : "OCR only"}</Badge></dd>
                <dt>Local OCR</dt><dd>{s.ocr_available ? "Apple Vision (on-device)" : "Unavailable"}</dd>
                <dt>Vision AI</dt><dd className="truncate" title={s.vision.models.join(", ")}>{s.vision.available ? s.vision.models[0] : "None reachable"}</dd>
                <dt>Displays</dt><dd>{s.displays.map((d) => `${d.width}×${d.height}${d.scale > 1 ? ` @${d.scale}x` : ""}`).join(", ") || "—"}</dd>
              </dl>
            )}
          </Card>

          <Card title="Privacy & control" icon="lock">
            {!s ? <Spinner /> : (
              <>
                <Toggle label="Screen awareness" description="Allow LYRA to look at your screen when you ask." checked={s.enabled}
                  onChange={(v) => setSetting({ enabled: v })} disabled={busy === "settings"} />
                <Toggle label="Use cloud vision AI" description="Send screenshots to the configured AI vision provider for detailed understanding. Off = on-device OCR only."
                  checked={s.cloud_consent} onChange={(v) => setSetting({ cloud_consent: v })} disabled={busy === "settings" || !s.enabled} />
                <Toggle label="Monitor screen changes" description="Opt-in. Checks every 5 s for app switches, new errors and major changes. No AI calls, nothing stored."
                  checked={s.monitoring.running} onChange={toggleMonitor} disabled={!s.enabled || busy === "monitor"} />
                <p className="muted small">Screenshots stay in memory only and are never written to disk. <button className="link-btn" onClick={clear}>Clear visual context</button></p>
              </>
            )}
          </Card>

          <Card title="Recent screen changes" icon="activity">
            {(vision.changes.length ? vision.changes : s?.monitoring?.recent_events?.slice().reverse() || []).length === 0 ? (
              <p className="muted small">{s?.monitoring?.running ? "Watching for changes…" : "Turn on monitoring to see app switches, errors and major changes here."}</p>
            ) : (
              <ul className="simple-list">
                {(vision.changes.length ? vision.changes : s.monitoring.recent_events.slice().reverse()).slice(0, 8).map((c, i) => (
                  <li key={i}>
                    <span className="truncate"><Badge tone={c.change === "error_appeared" ? "bad" : c.change === "error_cleared" ? "good" : "neutral"}>{titleCase(c.change)}</Badge> {c.detail}</span>
                    <span className="muted small">{timeAgo(c.at || c.timestamp)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Ask about your screen" icon="eye" className="span-3">
            <form className="screen-ask" onSubmit={(e) => { e.preventDefault(); if (question.trim()) command(); }}>
              <input value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={2000}
                placeholder="e.g. What is this error? · Where is the Submit button? · Click the Login button" disabled={!s?.enabled} />
              <button type="submit" className="btn btn-primary" disabled={!question.trim() || working || !s?.enabled}>
                {busy === "ask" ? <><Spinner size={12} /> Working…</> : "Ask LYRA"}
              </button>
              <button type="button" className="btn btn-ghost" onClick={analyze} disabled={working || !s?.enabled}>
                {busy === "analyze" ? <><Spinner size={12} /> Analyzing…</> : "Analyze screen"}
              </button>
              <button type="button" className="btn btn-ghost" onClick={capture} disabled={working || !s?.enabled}>
                {busy === "capture" ? <><Spinner size={12} /> Capturing…</> : "Capture only"}
              </button>
            </form>
            {answer && <div className="screen-answer"><Markdown text={answer} /></div>}
          </Card>

          {ctx ? (
            <>
              <Card title="What LYRA sees" icon="monitor" className="span-2"
                actions={<span className="muted small">{ctx.analysis_source === "local" ? "On-device analysis" : ctx.analysis_source.replace("vision:", "Vision: ")} · {timeAgo(ctx.captured_at)}</span>}>
                {preview && <img className="screen-preview" alt="Latest screen capture" src={`data:${preview.mime_type};base64,${preview.data_base64}`} />}
                <p>{ctx.summary}</p>
                {ctx.page_state && <p className="muted small">State: {ctx.page_state}</p>}
                {ctx.suggested_next_action && <p className="next-step"><Icon name="sparkle" size={14} /> {ctx.suggested_next_action}</p>}
              </Card>
              <Card title="Errors & warnings" icon="alert">
                {!ctx.errors.length && !ctx.warnings.length ? <p className="muted small">None visible.</p> : (
                  <ul className="issue-list">
                    {ctx.errors.map((e, i) => <li key={`e${i}`} className="issue err">{e}</li>)}
                    {ctx.warnings.map((w, i) => <li key={`w${i}`} className="issue warn">{w}</li>)}
                  </ul>
                )}
              </Card>
              <Card title={`Actionable elements (${actionable.length})`} icon="target" className="span-2">
                {actionable.length === 0 ? <p className="muted small">No actionable elements detected{ctx.analysis_source === "local" ? " — grant Accessibility or enable vision AI for richer detection" : ""}.</p> : (
                  <div className="element-chips">
                    {actionable.slice(0, 40).map((e) => (
                      <span key={e.id} className="element-chip" title={`${e.type} · ${e.source}`}>
                        <em>{titleCase(e.type)}</em> {e.label || "(unlabelled)"}{e.value ? ` = ${e.value}` : ""}
                      </span>
                    ))}
                  </div>
                )}
              </Card>
              <Card title={`Text on screen (${ctx.ocr_lines} lines)`} icon="file">
                <details>
                  <summary className="muted small">Show recognized text</summary>
                  <pre className="ocr-text">{ctx.visible_text || "(no text)"}</pre>
                </details>
              </Card>
            </>
          ) : (
            <Card className="span-3">
              <p className="muted small">No screen context yet. Ask a question, press “Analyze screen”, or just say “Lyra, look at my screen”.</p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
