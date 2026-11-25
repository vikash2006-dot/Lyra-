const LABELS = {
  idle: "",
  listening: "Listening…",
  processing: "Working…",
  speaking: "Speaking…",
  error: "Voice unavailable",
};

export default function VoiceStatus({ state, detail, level, onCancel }) {
  const label = detail || LABELS[state];
  if (!label) return null;
  return (
    <div className={`voice-status vstate-${state}`} role="status">
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
