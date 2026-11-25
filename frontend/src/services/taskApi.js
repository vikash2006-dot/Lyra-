import { apiData } from "./api";

export const listTasks = (status, limit = 30) =>
  apiData(`/api/tasks?limit=${limit}${status ? `&status=${encodeURIComponent(status)}` : ""}`);
export const getTask = (id) => apiData(`/api/tasks/${encodeURIComponent(id)}`);
export const submitTask = (command, sessionId) =>
  apiData("/api/tasks", { method: "POST", body: { command, session_id: sessionId || null } });
export const cancelTask = (id) => apiData(`/api/tasks/${encodeURIComponent(id)}/cancel`, { method: "POST" });
