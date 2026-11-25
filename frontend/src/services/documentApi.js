import { apiData } from "./api";

export const listDocuments = () => apiData("/api/documents");
export const supportedDocumentTypes = () => apiData("/api/documents/supported-types");
export const deleteDocument = (id) => apiData(`/api/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
export const analyzeDocument = (id, mode, question) =>
  apiData(`/api/documents/${encodeURIComponent(id)}/analyze`, {
    method: "POST",
    body: { mode, question: question || null },
    timeout: 180_000,
  });

export function uploadDocument(file) {
  const form = new FormData();
  form.append("file", file, file.name);
  return apiData("/api/documents/upload", { method: "POST", form, timeout: 120_000 });
}
