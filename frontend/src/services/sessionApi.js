import { apiData } from "./api";

export const listSessions = () => apiData("/api/sessions");
export const createSession = (title) => apiData("/api/sessions", { method: "POST", body: { title } });
export const getSession = (id) => apiData(`/api/sessions/${encodeURIComponent(id)}`);
export const renameSession = (id, title) =>
  apiData(`/api/sessions/${encodeURIComponent(id)}`, { method: "PATCH", body: { title } });
export const deleteSession = (id) => apiData(`/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
export const getSessionMessages = (id) => apiData(`/api/sessions/${encodeURIComponent(id)}/messages`);
