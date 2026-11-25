import { useEffect, useRef, useState } from "react";
import Icon from "../common/Icon";

export default function MessageInput({ onSend, onStop, busy, disabled, voiceSlot, placeholder }) {
  const [text, setText] = useState("");
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  const submit = async () => {
    const value = text.trim();
    if (!value || busy || disabled) return;
    const accepted = await onSend(value);
    if (accepted !== false) setText("");
  };

  return (
    <div className={`composer ${disabled ? "is-disabled" : ""}`}>
      <textarea
        ref={ref}
        rows={1}
        value={text}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        disabled={disabled}
        aria-label="Message LYRA"
        maxLength={8000}
      />
      <div className="composer-actions">
        {voiceSlot}
        {busy ? (
          <button className="send-btn stop" onClick={onStop} aria-label="Stop response" title="Stop">
            <Icon name="stop" size={16} />
          </button>
        ) : (
          <button className="send-btn" onClick={submit} disabled={!text.trim() || disabled} aria-label="Send message" title="Send">
            <Icon name="send" size={16} />
          </button>
        )}
      </div>
    </div>
  );
}
