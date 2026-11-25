import { useApp } from "../../context/AppContext";
import Icon from "../common/Icon";

export default function Header({ title, onMenu, right }) {
  const { health } = useApp();
  return (
    <header className="topbar">
      <button className="icon-btn menu-btn" onClick={onMenu} aria-label="Open menu">
        <Icon name="menu" size={18} />
      </button>
      <div className="topbar-title">{title}</div>
      <div className="topbar-right">
        {health.state === "offline" && <span className="pill pill-bad">Backend offline</span>}
        {health.state === "degraded" && <span className="pill pill-warn" title="No AI provider available">Degraded</span>}
        {right}
      </div>
    </header>
  );
}
