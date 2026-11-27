import { apiData } from "./api";

export const visionStatus = () => apiData("/api/vision/status", { timeout: 10_000 });
export const captureScreen = (sessionId) =>
  apiData("/api/vision/capture", { method: "POST", body: { session_id: sessionId || null }, timeout: 30_000 });
export const analyzeScreen = (question, sessionId) =>
  apiData("/api/vision/analyze", {
    method: "POST",
    body: { question: question || null, session_id: sessionId || null },
    timeout: 120_000,
  });
export const askScreen = (command, sessionId) =>
  apiData("/api/vision/ask", { method: "POST", body: { command, session_id: sessionId || null }, timeout: 180_000 });
export const getVisionContext = (sessionId) =>
  apiData(`/api/vision/context${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ""}`);
export const clearVisionContext = (sessionId) =>
  apiData(`/api/vision/context${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ""}`, { method: "DELETE" });
export const updateVisionSettings = (changes) => apiData("/api/vision/settings", { method: "PUT", body: changes });
export const requestScreenPermission = () => apiData("/api/vision/permission/request", { method: "POST" });
export const startMonitoring = (intervalSeconds) =>
  apiData("/api/vision/monitor/start", { method: "POST", body: { interval_seconds: intervalSeconds || null } });
export const stopMonitoring = () => apiData("/api/vision/monitor/stop", { method: "POST" });
