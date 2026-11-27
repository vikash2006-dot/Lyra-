const LABELS = {
  idle: "",
  listening: "Listening…",
  processing: "Working…",
  speaking: "Speaking…",
  interrupted: "Interrupted",
  error: "Voice unavailable",
};

const STATE_NAMES = {
  listening: "Listening",
  processing: "Processing",
  speaking: "Speaking",
  interrupted: "Interrupted",
  error: "Error",
  idle: "Idle",
};

export default function VoiceStatus({ state, detail, level, onCancel }) {
  const label = detail || LABELS[state];
  if (!label) return null;
  return (
    <div className={`voice-status vstate-${state}`} role="status">
      <span className={`voice-chip chip-${state}`}>{STATE_NAMES[state] || state}</span>
      <span className="voice-bars" style={{ "--level": level }} aria-hidden>
        <i /><i /><i /><i /><i />
      </span>
      <span>{label}</span>
      {(state === "listening" || state === "processing" || state === "speaking") && (
        <button className="btn btn-ghost btn-xs" onClick={onCancel}>Cancel</button>
      )}
    </div>
  );
}
