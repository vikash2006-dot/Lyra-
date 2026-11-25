import { apiData } from "./api";

export const listMemories = ({ q, type } = {}) => {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (type) params.set("type", type);
  const qs = params.toString();
  return apiData(`/api/memory${qs ? `?${qs}` : ""}`);
};
export const memoryTypes = () => apiData("/api/memory/types");
export const createMemory = (memory) => apiData("/api/memory", { method: "POST", body: memory });
export const updateMemory = (id, changes) =>
  apiData(`/api/memory/${encodeURIComponent(id)}`, { method: "PUT", body: changes });
export const deleteMemory = (id) => apiData(`/api/memory/${encodeURIComponent(id)}`, { method: "DELETE" });
