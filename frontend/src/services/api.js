import { API_TOKEN, API_URL } from "../config";

export class ApiError extends Error {
  constructor(message, { code = "REQUEST_FAILED", status = 0 } = {}) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

const DEFAULT_TIMEOUT_MS = 60_000;

/**
 * Central HTTP client. Every request goes through here so auth, timeouts and the
 * backend's {success, data, error} envelope are handled in one place.
 * Resolves with the parsed body; rejects with ApiError.
 */
export async function apiRequest(endpoint, { method = "GET", body, form, timeout = DEFAULT_TIMEOUT_MS, signal } = {}) {
  const headers = {};
  if (API_TOKEN) headers.Authorization = `Bearer ${API_TOKEN}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), timeout);
  const onAbort = () => controller.abort(signal.reason);
  signal?.addEventListener("abort", onAbort);

  let response;
  try {
    response = await fetch(`${API_URL}${endpoint}`, { method, headers, body: payload, signal: controller.signal });
  } catch (err) {
    if (controller.signal.reason?.name === "TimeoutError") {
      throw new ApiError("The request timed out.", { code: "TIMEOUT" });
    }
    if (err.name === "AbortError") throw new ApiError("Request cancelled.", { code: "ABORTED" });
    throw new ApiError("Cannot reach the LYRA backend. Is it running?", { code: "NETWORK_ERROR" });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    /* non-JSON response */
  }
  if (!response.ok || data?.success === false) {
    const err = data?.error || {};
    throw new ApiError(err.message || `Request failed (${response.status})`, {
      code: err.code || "REQUEST_FAILED",
      status: response.status,
    });
  }
  return data;
}

/** Convenience: returns only the `data` field of the envelope. */
export async function apiData(endpoint, options) {
  const res = await apiRequest(endpoint, options);
  return res.data;
}
