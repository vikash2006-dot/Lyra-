import { Link } from "react-router-dom";
import Header from "../components/layout/Header";
import { useLayout } from "../components/layout/Layout";
import TaskCard from "../components/tasks/TaskCard";
import { Badge, Card, ErrorBanner, PageHeader, Spinner, StatusDot } from "../components/common/ui";
import { useApp } from "../context/AppContext";
import { useChat } from "../context/ChatContext";
import { useAsync } from "../hooks/useAsync";
import { getProgress } from "../services/learningApi";
import { listMemories } from "../services/memoryApi";
import { getSystemStatus } from "../services/settingsApi";
import { formatDuration, timeAgo, titleCase } from "../utils/formatters";

const PROVIDER_TONE = { AVAILABLE: "good", READY: "good", NOT_CONFIGURED: "neutral" };

export default function DashboardPage() {
  const { openMenu } = useLayout();
  const { health, tasks, eventsStatus } = useApp();
  const { sessions } = useChat();
  const system = useAsync(getSystemStatus, []);
  const memories = useAsync(() => listMemories(), []);
  const learning = useAsync(getProgress, []);
  const s = system.data;

  return (
    <div className="page">
      <Header title="Dashboard" onMenu={openMenu} />
      <div className="page-body">
        <PageHeader
          title="Dashboard"
          subtitle="Live status of your LYRA backend, AI providers and recent activity."
          actions={<button className="btn btn-ghost" onClick={() => { system.reload(); memories.reload(); learning.reload(); }}>Refresh</button>}
        />
        <ErrorBanner error={system.error} onRetry={system.reload} />
        <div className="grid">
          <Card title="Backend" icon="server">
            <dl className="kv">
              <dt>Status</dt>
              <dd><StatusDot state={health.state} /> {titleCase(health.state)}</dd>
              <dt>Uptime</dt><dd>{s ? formatDuration(s.backend.uptime_seconds) : "—"}</dd>
              <dt>Environment</dt><dd>{s?.backend.environment || "—"}</dd>
              <dt>Realtime</dt><dd>{eventsStatus === "open" ? "Connected" : titleCase(eventsStatus)}</dd>
              <dt>Platform</dt><dd>{s?.backend.platform || "—"}</dd>
            </dl>
            {s?.backend.init_errors?.length > 0 && <p className="task-error">{s.backend.init_errors.join("; ")}</p>}
          </Card>

          <Card title="AI providers" icon="sparkle">
            {!s ? <Spinner /> : (
              <>
                <p className="muted small">
                  Currently routing to <strong>{s.ai.current_provider}</strong>
                  {s.ai.offline_mode && " · offline mode"}
                </p>
                <ul className="provider-list">
                  {s.ai.providers.map((p) => (
                    <li key={p.name}>
                      <span>{p.display_name}</span>
                      <span className="muted small">{p.model || ""}</span>
                      <Badge tone={PROVIDER_TONE[p.status] || (p.configured ? "warn" : "neutral")}>{titleCase(p.status.toLowerCase())}</Badge>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Card>

          <Card title="System" icon="settings">
            {!s ? <Spinner /> : (
              <dl className="kv">
                <dt>Tools</dt><dd>{s.tools.length} registered</dd>
                <dt>Speech-to-text</dt><dd>{s.voice.stt_provider} {s.voice.stt_ready ? "· ready" : "· unavailable"}</dd>
                <dt>Text-to-speech</dt><dd>{s.voice.tts_provider} {s.voice.tts_ready ? "· ready" : "· unavailable"}</dd>
                <dt>Mac automation</dt><dd>{s.computer.platform_supported ? "Available" : "Not supported on this OS"}</dd>
                <dt>Scheduler</dt><dd>{s.automation.scheduler_running ? "Running" : "Stopped"}</dd>
                <dt>Active tasks</dt><dd>{s.tasks.active}</dd>
              </dl>
            )}
          </Card>

          <Card title="Recent tasks" icon="activity" className="span-2" actions={<Link to="/chat" className="link">Open chat</Link>}>
            {tasks.length === 0 ? <p className="muted small">No tasks yet. Ask LYRA to do something on your Mac.</p> : (
              <div className="task-grid">{tasks.slice(0, 4).map((t) => <TaskCard key={t.id} task={t} compact />)}</div>
            )}
          </Card>

          <Card title="Recent conversations" icon="chat">
            {sessions.length === 0 ? <p className="muted small">No conversations yet.</p> : (
              <ul className="simple-list">
                {sessions.slice(0, 6).map((c) => (
                  <li key={c.id}>
                    <Link to={`/chat/${c.id}`}>{c.title}</Link>
                    <span className="muted small">{c.message_count} msgs · {timeAgo(c.updated_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Memory" icon="brain" actions={<Link to="/memory" className="link">Manage</Link>}>
            {memories.loading ? <Spinner /> : memories.error ? <p className="muted small">Unavailable</p> : (
              <>
                <p className="stat">{memories.data.length}<span>stored memories</span></p>
                <ul className="simple-list">
                  {memories.data.slice(0, 3).map((m) => (
                    <li key={m.id}><span className="truncate">{m.content}</span><Badge>{titleCase(m.type)}</Badge></li>
                  ))}
                </ul>
              </>
            )}
          </Card>

          <Card title="Learning" icon="book" actions={<Link to="/learning" className="link">Open</Link>}>
            {learning.loading ? <Spinner /> : learning.error ? <p className="muted small">Unavailable</p> : (() => {
              const r = learning.data.report;
              return r.target_role ? (
                <dl className="kv">
                  <dt>Target role</dt><dd>{r.target_role}</dd>
                  <dt>Skills acquired</dt><dd>{r.skills_acquired.length}</dd>
                  <dt>In progress</dt><dd>{r.skills_in_progress.length}</dd>
                  <dt>Remaining gaps</dt><dd>{r.remaining_gaps.length}</dd>
                </dl>
              ) : <p className="muted small">No target role set yet. Set one on the Learning page to get a plan.</p>;
            })()}
          </Card>
        </div>
      </div>
    </div>
  );
}
