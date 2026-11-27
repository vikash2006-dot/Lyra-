import TaskCard from "../tasks/TaskCard";
import Icon from "../common/Icon";
import Markdown from "./Markdown";
import TypingIndicator from "./TypingIndicator";

// Turns answered by the action planner or a tool directly carry an intent, not a model name.
const NON_MODEL_SOURCES = new Set(["action_planner", "tool_executor", "tool", "system"]);

export default function Message({ message, phase, onConfirm }) {
  const { role, content, pending, error, task, source, stopped, ack, muted } = message;
  const isUser = role === "user";
  return (
    <div className={`message ${isUser ? "from-user" : "from-lyra"}`}>
      {!isUser && <div className="avatar" aria-hidden><span /></div>}
      <div className="bubble-wrap">
        {ack && !isUser && <p className="ack-line">{ack}</p>}
        {task && !isUser && <TaskCard task={task} onConfirm={onConfirm} />}
        {(content || pending || error) && (
          <div className={`bubble ${error ? "has-error" : ""} ${muted ? "is-muted" : ""}`}>
            {content ? (isUser ? <p className="plain">{content}</p> : <Markdown text={content} />) : null}
            {pending && !content && <TypingIndicator phase={phase} />}
            {error && (
              <p className="bubble-error"><Icon name="alert" size={14} /> {error}</p>
            )}
          </div>
        )}
        <div className="message-meta">
          {source === "voice" && <span className="meta-tag"><Icon name="mic" size={11} /> voice</span>}
          {stopped && <span className="meta-tag">stopped</span>}
          {message.model && !isUser && !NON_MODEL_SOURCES.has(message.provider) && (
            <span className="meta-tag">{message.model}</span>
          )}
        </div>
      </div>
    </div>
  );
}
