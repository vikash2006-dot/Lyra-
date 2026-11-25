import { apiData, apiRequest } from "./api";

export const getHealth = () => apiRequest("/api/health", { timeout: 5000 });
export const getSystemStatus = () => apiData("/api/system/status");
export const getSettings = () => apiData("/api/settings");
export const updateSettings = (changes) => apiData("/api/settings", { method: "PUT", body: changes });
export const getProviders = () => apiData("/api/settings/providers");
