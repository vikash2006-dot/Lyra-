import Icon from "../common/Icon";

const TITLES = {
  idle: "Talk to LYRA",
  listening: "Listening — tap to finish",
  processing: "Working — tap to interrupt",
  speaking: "Speaking — tap to stop",
  error: "Voice error — tap to retry",
};

export default function VoiceButton({ state, level = 0, onClick, disabled }) {
  return (
    <button
      type="button"
      className={`voice-btn vs-${state}`}
      onClick={onClick}
      disabled={disabled}
      aria-label={TITLES[state]}
      title={TITLES[state]}
      style={{ "--level": state === "listening" ? level : 0 }}
    >
      <span className="voice-ring" aria-hidden />
      <Icon name={state === "speaking" || state === "processing" ? "stop" : "mic"} size={17} />
    </button>
  );
}
