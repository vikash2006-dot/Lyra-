// Single source of backend location. Set VITE_API_URL in frontend/.env.
export const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/+$/, "");
export const API_TOKEN = import.meta.env.VITE_API_TOKEN || "";
export const WS_URL = API_URL.replace(/^http/, "ws");
