import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ChatWindow from "../components/chat/ChatWindow";
import MessageInput from "../components/chat/MessageInput";
import Icon from "../components/common/Icon";
import Header from "../components/layout/Header";
import { useLayout } from "../components/layout/Layout";
import TaskPanel from "../components/tasks/TaskPanel";
import VoiceButton from "../components/voice/VoiceButton";
import VoiceStatus from "../components/voice/VoiceStatus";
import { useApp } from "../context/AppContext";
import { useChat } from "../context/ChatContext";
import { usePreferences } from "../hooks/usePreferences";
import { useVoice } from "../hooks/useVoice";
import { VISION_STATE_LABELS } from "./ScreenPage";

const UNSET = Symbol("unset");

export default function ChatPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const { openMenu } = useLayout();
  const { backendOnline, notify, vision } = useApp();
  const chat = useChat();
  const { activeSessionId, loadSession, sessions } = chat;
  const [prefs, setPrefs] = usePreferences();
  const [panelOpen, setPanelOpen] = useState(() => prefs.showActivity && window.innerWidth > 1100);

  const voice = useVoice({
    autoSpeak: prefs.autoSpeak,
    handsFree: prefs.handsFree,
    volume: prefs.volume,
    onSession: (id) => chat.setActiveSessionId(id),
  });

  // Keep the URL and the active conversation in sync in both directions.
  const prevParam = useRef(UNSET);
  const prevActive = useRef(UNSET);
  useEffect(() => {
    const paramChanged = prevParam.current !== sessionId;
    const activeChanged = prevActive.current !== activeSessionId;
    prevParam.current = sessionId;
    prevActive.current = activeSessionId;
    if (paramChanged) {
      if ((sessionId || null) !== activeSessionId || !chat.messages.length) loadSession(sessionId || null);
    } else if (activeChanged && activeSessionId && activeSessionId !== sessionId) {
      navigate(`/chat/${activeSessionId}`, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, activeSessionId]);

  const onConfirm = useCallback(
    (task, yes) => {
      if (task.session_id && task.session_id !== activeSessionId) {
        navigate(`/chat/${task.session_id}`);
        notify("Opened the conversation that needs your confirmation.");
        return;
      }
      chat.send(yes ? "yes" : "no");
    },
    [activeSessionId, chat, navigate, notify],
  );

  const title = sessions.find((s) => s.id === activeSessionId)?.title || "New chat";
  const voiceBusy = voice.state === "listening" || voice.state === "processing" || voice.state === "speaking";

  return (
    <div className="chat-layout">
      <div className="chat-main">
        <Header
          title={title}
          onMenu={openMenu}
          right={
            <>
            {vision.state && vision.state !== "idle" && (
              <Link to="/screen" className={`vision-pill small tone-${["capturing", "analyzing", "executing", "verifying"].includes(vision.state) ? "busy" : vision.state === "permission_denied" || vision.state === "failed" ? "bad" : "good"}`} title="Screen awareness">
                <Icon name="eye" size={13} /> {VISION_STATE_LABELS[vision.state] || vision.state}
              </Link>
            )}
            <button
              className={`icon-btn ${panelOpen ? "active" : ""}`}
              onClick={() => {
                setPanelOpen((v) => !v);
                setPrefs({ showActivity: !panelOpen });
              }}
              aria-label="Toggle activity panel"
              title="Task activity"
            >
              <Icon name="activity" size={18} />
            </button>
            </>
          }
        />
        <ChatWindow
          messages={chat.messages}
          loading={chat.loadingMessages}
          phase={chat.phase}
          onSuggestion={chat.send}
          onConfirm={onConfirm}
          disabled={!backendOnline || chat.busy}
        />
        <div className="composer-wrap">
          <VoiceStatus state={voice.state} detail={voice.detail} level={voice.level} onCancel={voice.cancel} />
          <MessageInput
            onSend={chat.send}
            onStop={chat.stop}
            busy={chat.busy}
            disabled={!backendOnline || voiceBusy}
            placeholder={backendOnline ? "Message LYRA…" : "Waiting for the LYRA backend…"}
            voiceSlot={
              <VoiceButton
                state={voice.state}
                level={voice.level}
                onClick={voice.toggle}
                disabled={
                  !backendOnline || !voice.connected || chat.busy ||
                  (!prefs.allowInterrupt && (voice.state === "processing" || voice.state === "speaking"))
                }
              />
            }
          />
          <p className="composer-hint">
            {chat.socketStatus === "open" ? "Enter to send · Shift+Enter for a new line" : "Live connection unavailable — using standard requests"}
          </p>
        </div>
      </div>
      {panelOpen && <TaskPanel onClose={() => setPanelOpen(false)} onConfirm={onConfirm} />}
    </div>
  );
}
