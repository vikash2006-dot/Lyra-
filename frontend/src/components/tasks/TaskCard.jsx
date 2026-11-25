import { useState } from "react";
import { cancelTask } from "../../services/taskApi";
import { ACTIVE_TASK_STATUSES, STATUS_LABELS, timeAgo } from "../../utils/formatters";
import Icon from "../common/Icon";
import { Spinner } from "../common/ui";

const ORDER = ["pending", "planning", "running", "waiting_for_confirmation", "verifying", "completed", "failed", "cancelled"];

function StepIcon({ status }) {
  if (status === "completed") return <span className="step-icon ok"><Icon name="check" size={12} strokeWidth={2.6} /></span>;
  if (status === "failed") return <span className="step-icon bad"><Icon name="x" size={12} strokeWidth={2.6} /></span>;
  if (status === "running" || status === "active") return <span className="step-icon run"><Spinner size={10} /></span>;
  if (status === "waiting") return <span className="step-icon warn">!</span>;
  if (status === "skipped") return <span className="step-icon skip">–</span>;
  return <span className="step-icon idle" />;
}

/** Builds the visible step list from the task's real status and executed steps. */
function buildSteps(task) {
  const idx = ORDER.indexOf(task.status);
  const finished = ["completed", "failed", "cancelled"].includes(task.status);
  const hasPlan = task.steps?.length > 0 || task.status === "waiting_for_confirmation";
  const rows = [
    { label: "Understanding request", status: idx >= 1 || finished ? "completed" : "running" },
    {
      label: "Planning task",
      status: hasPlan || idx >= 2 ? "completed" : task.status === "planning" ? "running" : finished ? "skipped" : "pending",
    },
  ];
  for (const s of task.steps || []) {
    rows.push({
      label: s.description || s.tool,
      status: s.status,
      detail: s.status === "failed" || s.status === "waiting" ? s.summary : s.verification_note,
    });
  }
  if ((task.steps || []).length) {
    let v = "pending";
    if (task.status === "verifying") v = "running";
    else if (task.status === "completed") v = "completed";
    else if (task.status === "failed" && task.verification) v = "failed";
    else if (finished) v = "skipped";
    rows.push({ label: "Verifying result", status: v, detail: task.verification?.summary });
  }
  return rows;
}

export default function TaskCard({ task, compact = false, onConfirm }) {
  const [cancelling, setCancelling] = useState(false);
  if (!task) return null;
  const active = ACTIVE_TASK_STATUSES.has(task.status);
  const steps = buildSteps(task);

  const cancel = async () => {
    setCancelling(true);
    try {
      await cancelTask(task.id);
    } catch {
      /* status update arrives via events; errors mean it already finished */
    } finally {
      setCancelling(false);
    }
  };

  return (
    <div className={`task-card status-${task.status} ${compact ? "compact" : ""}`}>
      <div className="task-head">
        <div className="task-title">
          <span className="task-label">Task</span>
          <span className="task-command" title={task.command}>{task.command}</span>
        </div>
        <span className={`task-status ts-${task.status}`}>{STATUS_LABELS[task.status] || task.status}</span>
      </div>
      <ol className="task-steps">
        {steps.map((s, i) => (
          <li key={i} className={`step step-${s.status}`}>
            <StepIcon status={s.status} />
            <div>
              <span className="step-label">{s.label}</span>
              {s.detail && !compact && <span className="step-detail">{s.detail}</span>}
            </div>
          </li>
        ))}
      </ol>
      {task.status === "waiting_for_confirmation" && (
        <div className="task-confirm">
          <p>{task.confirmation_prompt || "LYRA needs your confirmation to continue."}</p>
          {onConfirm && (
            <div className="row gap-sm">
              <button className="btn btn-primary btn-sm" onClick={() => onConfirm(task, true)}>Confirm</button>
              <button className="btn btn-ghost btn-sm" onClick={() => onConfirm(task, false)}>Cancel</button>
            </div>
          )}
        </div>
      )}
      {task.status === "failed" && task.error && !compact && <p className="task-error">{task.error}</p>}
      <div className="task-foot">
        <span>{timeAgo(task.updated_at || task.created_at)}</span>
        {active && (
          <button className="btn btn-ghost btn-xs" onClick={cancel} disabled={cancelling}>
            {cancelling ? "Stopping…" : "Stop"}
          </button>
        )}
      </div>
    </div>
  );
}
