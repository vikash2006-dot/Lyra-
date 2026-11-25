import { apiData } from "./api";

export const sendChatMessage = (message, sessionId) =>
  apiData("/api/chat", { method: "POST", body: { message, session_id: sessionId || null }, timeout: 180_000 });
