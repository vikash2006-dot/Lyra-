import { useEffect, useRef } from "react";
import { Spinner } from "../common/ui";
import Message from "./Message";

const SUGGESTIONS = [
  "What's the weather like today?",
  "Create a folder called AI Projects on my Desktop",
  "Open YouTube and search for lofi music",
  "What do you remember about me?",
];

export default function ChatWindow({ messages, loading, phase, onSuggestion, onConfirm, disabled }) {
  const endRef = useRef(null);
  const last = messages[messages.length - 1];
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, last?.content, last?.task?.status]);

  if (loading) {
    return <div className="chat-scroll center"><Spinner size={22} /></div>;
  }
  if (!messages.length) {
    return (
      <div className="chat-scroll">
        <div className="chat-welcome">
          <div className="welcome-orb" aria-hidden><span /></div>
          <h1>Hi, I'm LYRA.</h1>
          <p>Ask a question, give me a task on your Mac, or tap the mic and just talk.</p>
          <div className="suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s} className="suggestion" onClick={() => onSuggestion(s)} disabled={disabled}>{s}</button>
            ))}
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="chat-scroll">
      <div className="message-list">
        {messages.map((m) => <Message key={m.id} message={m} phase={phase} onConfirm={onConfirm} />)}
        <div ref={endRef} />
      </div>
    </div>
  );
}
