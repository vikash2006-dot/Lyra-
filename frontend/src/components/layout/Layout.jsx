import { createContext, useContext, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import Toasts from "../common/Toasts";
import Sidebar from "./Sidebar";

const LayoutContext = createContext({ openMenu: () => {} });
export const useLayout = () => useContext(LayoutContext);

export default function Layout() {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  return (
    <LayoutContext.Provider value={{ openMenu: () => setMenuOpen(true) }}>
      <div className="app-shell">
        <Sidebar open={menuOpen} onNavigate={() => setMenuOpen(false)} />
        {menuOpen && <div className="scrim" onClick={() => setMenuOpen(false)} aria-hidden />}
        <main className="main" key={location.pathname.startsWith("/chat") ? "chat" : location.pathname}>
          <Outlet />
        </main>
        <Toasts />
      </div>
    </LayoutContext.Provider>
  );
}
