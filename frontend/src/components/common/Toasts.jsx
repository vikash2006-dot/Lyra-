import { useApp } from "../../context/AppContext";
import Icon from "./Icon";

export default function Toasts() {
  const { toasts, dismissToast } = useApp();
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.level}`}>
          <Icon name={t.level === "error" ? "alert" : t.level === "success" ? "check" : "sparkle"} size={16} />
          <div>
            {t.title && <strong>{t.title}</strong>}
            <span>{t.message}</span>
          </div>
          <button className="icon-btn" onClick={() => dismissToast(t.id)} aria-label="Dismiss">
            <Icon name="x" size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
