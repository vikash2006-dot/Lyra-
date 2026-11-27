import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { getHealth } from "../services/settingsApi";
import { listTasks } from "../services/taskApi";
import { LyraSocket } from "../services/websocket";

const AppContext = createContext(null);
const HEALTH_INTERVAL_MS = 15_000;

export function AppProvider({ children }) {
  const [health, setHealth] = useState({ state: "connecting", data: null, error: null });
  const [eventsStatus, setEventsStatus] = useState("idle");
  const [tasks, setTasks] = useState({});
  const [toasts, setToasts] = useState([]);
  // Live screen-awareness state pushed by the backend (state changes, new context, screen changes).
  const [vision, setVision] = useState({ state: null, detail: null, context: null, changes: [] });
  const toastId = useRef(0);

  const notify = useCallback((message, level = "info", title) => {
    toastId.current += 1;
    const id = toastId.current;
    setToasts((t) => [...t.slice(-3), { id, message, level, title }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), level === "error" ? 7000 : 4500);
  }, []);
  const dismissToast = useCallback((id) => setToasts((t) => t.filter((x) => x.id !== id)), []);

  const upsertTask = useCallback((task) => {
    if (!task?.id) return;
    setTasks((prev) => ({ ...prev, [task.id]: { ...prev[task.id], ...task } }));
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      const res = await getHealth();
      setHealth({ state: res.data.status === "ok" ? "online" : res.data.status, data: res.data, error: null });
    } catch (err) {
      setHealth((h) => ({ state: "offline", data: h.data, error: err.message }));
    }
  }, []);

  const refreshTasks = useCallback(async () => {
    try {
      const list = await listTasks(undefined, 30);
      setTasks(Object.fromEntries(list.map((t) => [t.id, t])));
    } catch {
      /* health indicator already reports connectivity */
    }
  }, []);

  useEffect(() => {
    refreshHealth();
    refreshTasks();
    const timer = setInterval(refreshHealth, HEALTH_INTERVAL_MS);
    const socket = new LyraSocket("/ws/events", {
      onStatus: (s) => {
        setEventsStatus(s);
        if (s === "open") {
          refreshHealth();
          refreshTasks();
        }
      },
      onEvent: (ev) => {
        if (ev.type === "task_update" && ev.task) upsertTask(ev.task);
        else if (ev.type === "notification") notify(ev.message, ev.level || "info", ev.title);
        else if (ev.type === "vision_state") setVision((v) => ({ ...v, state: ev.state, detail: ev.detail }));
        else if (ev.type === "vision_context") setVision((v) => ({ ...v, context: ev.cleared ? null : ev.context }));
        else if (ev.type === "screen_change") {
          setVision((v) => ({ ...v, changes: [ev, ...v.changes].slice(0, 20) }));
          if (ev.change === "error_appeared") notify(ev.detail, "error", "Error appeared on screen");
        }
      },
    });
    socket.connect();
    return () => {
      clearInterval(timer);
      socket.close();
    };
  }, [refreshHealth, refreshTasks, upsertTask, notify]);

  const taskList = useMemo(
    () => Object.values(tasks).sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")),
    [tasks],
  );

  const value = useMemo(
    () => ({
      health,
      backendOnline: health.state === "online" || health.state === "degraded",
      eventsStatus,
      refreshHealth,
      tasks: taskList,
      upsertTask,
      refreshTasks,
      toasts,
      notify,
      dismissToast,
      vision,
    }),
    [health, eventsStatus, refreshHealth, taskList, upsertTask, refreshTasks, toasts, notify, dismissToast, vision],
  );
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}
