import { useApp } from "../../context/AppContext";
import { ACTIVE_TASK_STATUSES } from "../../utils/formatters";
import Icon from "../common/Icon";
import TaskCard from "./TaskCard";

export default function TaskPanel({ onClose, onConfirm }) {
  const { tasks } = useApp();
  const active = tasks.filter((t) => ACTIVE_TASK_STATUSES.has(t.status) || t.status === "waiting_for_confirmation");
  const recent = tasks.filter((t) => !active.includes(t)).slice(0, 12);

  return (
    <aside className="activity-panel" aria-label="Task activity">
      <header>
        <h2><Icon name="activity" size={16} /> Activity</h2>
        {onClose && (
          <button className="icon-btn" onClick={onClose} aria-label="Close activity panel">
            <Icon name="x" size={16} />
          </button>
        )}
      </header>
      <div className="activity-scroll">
        {active.length > 0 && <h3 className="section-label">In progress</h3>}
        {active.map((t) => <TaskCard key={t.id} task={t} onConfirm={onConfirm} />)}
        <h3 className="section-label">Recent</h3>
        {recent.length === 0 && (
          <p className="muted small">Actions LYRA performs — opening apps, browsing, creating files — appear here with live progress.</p>
        )}
        {recent.map((t) => <TaskCard key={t.id} task={t} compact />)}
      </div>
    </aside>
  );
}
