const LABELS = { thinking: "Thinking", working: "Working on it", streaming: "Responding" };

export default function TypingIndicator({ phase = "thinking" }) {
  return (
    <span className="typing" aria-live="polite">
      <span className="typing-dots"><i /><i /><i /></span>
      <span>{LABELS[phase] || "Thinking"}…</span>
    </span>
  );
}
