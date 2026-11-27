import { useCallback, useEffect, useState } from "react";

const KEY = "lyra.preferences";
const DEFAULTS = { autoSpeak: true, handsFree: false, showActivity: true, volume: 0.9, allowInterrupt: true };

function load() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || "{}") };
  } catch {
    return DEFAULTS;
  }
}

/** UI-only preferences stored in the browser (no secrets). */
export function usePreferences() {
  const [prefs, setPrefs] = useState(load);
  useEffect(() => {
    const sync = () => setPrefs(load());
    window.addEventListener("lyra-preferences", sync);
    return () => window.removeEventListener("lyra-preferences", sync);
  }, []);
  const update = useCallback((changes) => {
    setPrefs((p) => {
      const next = { ...p, ...changes };
      localStorage.setItem(KEY, JSON.stringify(next));
      window.dispatchEvent(new Event("lyra-preferences"));
      return next;
    });
  }, []);
  return [prefs, update];
}
