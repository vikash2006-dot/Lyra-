import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useApp } from "../../context/AppContext";
import { useChat } from "../../context/ChatContext";
import { timeAgo } from "../../utils/formatters";
import Icon from "../common/Icon";
import { StatusDot } from "../common/ui";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: "grid" },
  { to: "/screen", label: "Screen", icon: "eye" },
  { to: "/learning", label: "Learning", icon: "book" },
  { to: "/memory", label: "Memory", icon: "brain" },
  { to: "/documents", label: "Documents", icon: "file" },
  { to: "/settings", label: "Settings", icon: "settings" },
];

function SessionItem({ session, active, onOpen }) {
  const { renameSession, removeSession } = useChat();
  const { notify } = useApp();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(session.title);

  const save = async () => {
    setEditing(false);
    if (title.trim() && title !== session.title) {
      try {
        await renameSession(session.id, title.trim());
      } catch (err) {
        notify(err.message, "error");
        setTitle(session.title);
      }
    }
  };
  const remove = async () => {
    if (!window.confirm(`Delete "${session.title}"? This cannot be undone.`)) return;
    try {
      await removeSession(session.id);
    } catch (err) {
      notify(err.message, "error");
    }
  };

  if (editing) {
    return (
      <li className="session-item editing">
        <input
          autoFocus
          value={title}
          maxLength={120}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={save}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") {
              setTitle(session.title);
              setEditing(false);
            }
          }}
          aria-label="Conversation title"
        />
      </li>
    );
  }
  return (
    <li className={`session-item ${active ? "active" : ""}`}>
      <button className="session-open" onClick={() => onOpen(session.id)} title={session.title}>
        <span className="session-title">{session.title}</span>
        <span className="session-time">{timeAgo(session.updated_at)}</span>
      </button>
      <span className="session-tools">
        <button className="icon-btn" onClick={() => setEditing(true)} aria-label="Rename"><Icon name="edit" size={13} /></button>
        <button className="icon-btn" onClick={remove} aria-label="Delete"><Icon name="trash" size={13} /></button>
      </span>
    </li>
  );
}

export default function Sidebar({ open, onNavigate }) {
  const { health } = useApp();
  const { sessions, activeSessionId } = useChat();
  const navigate = useNavigate();
  const go = (path) => {
    navigate(path);
    onNavigate?.();
  };
  const stateLabel = { online: "Connected", degraded: "Degraded", offline: "Backend offline", connecting: "Connecting…", error: "Backend error" };

  return (
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <div className="brand" onClick={() => go("/")} role="link" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && go("/")}>
        <span className="brand-mark" aria-hidden><span /></span>
        <span className="brand-name">LYRA</span>
      </div>

      <button className="btn btn-new-chat" onClick={() => go("/chat")}>
        <Icon name="plus" size={16} /> New chat
      </button>

      <nav className="nav">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} className="nav-link" onClick={onNavigate}>
            <Icon name={n.icon} size={17} /> {n.label}
          </NavLink>
        ))}
      </nav>

      <div className="history">
        <h3 className="section-label">Conversations</h3>
        {sessions.length === 0 && <p className="muted small history-empty">No conversations yet.</p>}
        <ul>
          {sessions.map((s) => (
            <SessionItem key={s.id} session={s} active={s.id === activeSessionId} onOpen={(id) => go(`/chat/${id}`)} />
          ))}
        </ul>
      </div>

      <div className="sidebar-foot" title={health.error || ""}>
        <StatusDot state={health.state} />
        <span>{stateLabel[health.state] || health.state}</span>
      </div>
    </aside>
  );
}
