import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { sendChatMessage } from "../services/chatApi";
import {
  deleteSession as apiDeleteSession,
  getSessionMessages,
  listSessions,
  renameSession as apiRenameSession,
} from "../services/sessionApi";
import { LyraSocket } from "../services/websocket";
import { useApp } from "./AppContext";

const ChatContext = createContext(null);
let localId = 0;
const nextId = () => `local-${(localId += 1)}`;

function fromServer(m) {
  return { id: `srv-${m.id}`, role: m.role, content: m.content, created_at: m.created_at, meta: m.metadata };
}

export function ChatProvider({ children }) {
  const { notify, upsertTask } = useApp();
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState(null); // thinking | working | streaming
  const [socketStatus, setSocketStatus] = useState("idle");
  const socketRef = useRef(null);
  const pendingRef = useRef(null); // id of the assistant message being streamed
  const activeRef = useRef(null);
  activeRef.current = activeSessionId;

  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await listSessions());
    } catch {
      /* surfaced by the connection indicator */
    }
  }, []);

  const patchPending = useCallback((fn) => {
    const id = pendingRef.current;
    if (!id) return;
    setMessages((list) => list.map((m) => (m.id === id ? { ...m, ...fn(m) } : m)));
  }, []);

  const finishTurn = useCallback(() => {
    pendingRef.current = null;
    if (socketRef.current) socketRef.current.wasStreaming = false;
    setBusy(false);
    setPhase(null);
    refreshSessions();
  }, [refreshSessions]);

  const handleEvent = useCallback(
    (ev) => {
      switch (ev.type) {
        case "message_received":
          if (ev.session_id && ev.session_id !== activeRef.current) setActiveSessionId(ev.session_id);
          break;
        case "thinking":
          setPhase("thinking");
          break;
        case "task_started":
        case "task_update":
          if (ev.task) {
            upsertTask(ev.task);
            patchPending(() => ({ task: ev.task }));
            setPhase("working");
          }
          break;
        case "response_start":
          setPhase("streaming");
          patchPending(() => ({ model: ev.model, provider: ev.provider }));
          break;
        case "response_delta":
          setPhase("streaming");
          patchPending((m) => ({ content: (m.content || "") + ev.delta }));
          break;
        case "completed":
          patchPending(() => ({
            content: ev.response,
            pending: false,
            task: ev.task || undefined,
            model: ev.model,
            provider: ev.provider,
          }));
          if (ev.task) upsertTask(ev.task);
          finishTurn();
          break;
        case "cancelled":
          patchPending((m) => ({ pending: false, content: m.content || "Stopped.", stopped: true }));
          finishTurn();
          break;
        case "error": {
          const msg = ev.error?.message || "Something went wrong.";
          if (pendingRef.current) {
            patchPending((m) => ({ pending: false, error: msg, content: m.content || "" }));
            finishTurn();
          } else notify(msg, "error");
          break;
        }
        default:
          break;
      }
    },
    [finishTurn, notify, patchPending, upsertTask],
  );

  const handleEventRef = useRef(handleEvent);
  handleEventRef.current = handleEvent;

  useEffect(() => {
    const socket = new LyraSocket("/ws/chat", { onEvent: (e) => handleEventRef.current(e), onStatus: setSocketStatus });
    socketRef.current = socket;
    socket.connect();
    refreshSessions();
    return () => socket.close();
  }, [refreshSessions]);

  // If the socket drops mid-turn, the server cancels the turn; reflect that honestly.
  useEffect(() => {
    if (socketStatus !== "open" && pendingRef.current && busy && socketRef.current?.wasStreaming) {
      patchPending((m) => ({ pending: false, error: "Connection lost while LYRA was responding.", content: m.content }));
      finishTurn();
    }
  }, [socketStatus, busy, patchPending, finishTurn]);

  const loadSession = useCallback(async (sessionId) => {
    setActiveSessionId(sessionId);
    if (!sessionId) {
      setMessages([]);
      return;
    }
    setLoadingMessages(true);
    try {
      const msgs = await getSessionMessages(sessionId);
      setMessages(msgs.map(fromServer));
    } catch (err) {
      setMessages([]);
      notify(err.message, "error");
    } finally {
      setLoadingMessages(false);
    }
  }, [notify]);

  const send = useCallback(
    async (text) => {
      const message = text.trim();
      if (!message || busy) return false;
      const assistantId = nextId();
      pendingRef.current = assistantId;
      setBusy(true);
      setPhase("thinking");
      setMessages((list) => [
        ...list,
        { id: nextId(), role: "user", content: message, created_at: Date.now() / 1000 },
        { id: assistantId, role: "assistant", content: "", pending: true },
      ]);

      const socket = socketRef.current;
      if (socket?.isOpen) {
        socket.wasStreaming = true;
        socket.send({ type: "message", message, session_id: activeRef.current });
        return true;
      }
      // Fallback: plain REST request when the realtime channel is unavailable.
      try {
        const res = await sendChatMessage(message, activeRef.current);
        if (res.session_id !== activeRef.current) setActiveSessionId(res.session_id);
        if (res.task) upsertTask(res.task);
        patchPending(() => ({ content: res.response, pending: false, task: res.task || undefined, model: res.model }));
      } catch (err) {
        patchPending(() => ({ pending: false, error: err.message }));
      } finally {
        finishTurn();
      }
      return true;
    },
    [busy, finishTurn, patchPending, upsertTask],
  );

  const stop = useCallback(() => {
    if (socketRef.current?.isOpen) socketRef.current.send({ type: "cancel" });
  }, []);

  // Voice turns happen on a separate channel; these let the voice hook write into the chat.
  const appendMessage = useCallback((msg) => {
    const id = nextId();
    setMessages((list) => [...list, { id, created_at: Date.now() / 1000, ...msg }]);
    return id;
  }, []);
  const updateMessage = useCallback((id, changes) => {
    setMessages((list) => list.map((m) => (m.id === id ? { ...m, ...changes } : m)));
  }, []);

  const renameSession = useCallback(async (id, title) => {
    await apiRenameSession(id, title);
    refreshSessions();
  }, [refreshSessions]);

  const removeSession = useCallback(async (id) => {
    await apiDeleteSession(id);
    if (activeRef.current === id) {
      setActiveSessionId(null);
      setMessages([]);
    }
    refreshSessions();
  }, [refreshSessions]);

  const value = useMemo(
    () => ({
      sessions,
      refreshSessions,
      activeSessionId,
      setActiveSessionId,
      messages,
      loadSession,
      loadingMessages,
      send,
      stop,
      busy,
      phase,
      socketStatus,
      appendMessage,
      updateMessage,
      renameSession,
      removeSession,
    }),
    [sessions, refreshSessions, activeSessionId, messages, loadSession, loadingMessages, send, stop, busy, phase,
      socketStatus, appendMessage, updateMessage, renameSession, removeSession],
  );
  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChat must be used inside ChatProvider");
  return ctx;
}
