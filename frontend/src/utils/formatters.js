export function timeAgo(value) {
  if (!value) return "";
  const ts = typeof value === "number" ? (value < 1e12 ? value * 1000 : value) : Date.parse(value);
  if (Number.isNaN(ts)) return "";
  const diff = Math.max(0, Date.now() - ts) / 1000;
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  if (diff < 86400 * 7) return `${Math.round(diff / 86400)}d ago`;
  return new Date(ts).toLocaleDateString();
}

export function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDuration(seconds) {
  if (seconds == null) return "";
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

export const titleCase = (s = "") => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const STATUS_LABELS = {
  pending: "Pending",
  planning: "Planning",
  running: "Running",
  waiting_for_confirmation: "Needs confirmation",
  verifying: "Verifying",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const ACTIVE_TASK_STATUSES = new Set(["pending", "planning", "running", "verifying"]);
