import { useEffect, useState } from "react";
import Icon from "../components/common/Icon";
import Header from "../components/layout/Header";
import { useLayout } from "../components/layout/Layout";
import { Badge, Card, EmptyState, ErrorBanner, PageHeader, Spinner } from "../components/common/ui";
import { useApp } from "../context/AppContext";
import { useAsync } from "../hooks/useAsync";
import { createMemory, deleteMemory, listMemories, memoryTypes, updateMemory } from "../services/memoryApi";
import { timeAgo, titleCase } from "../utils/formatters";

function MemoryItem({ memory, types, onChanged }) {
  const { notify } = useApp();
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(memory.content);
  const [type, setType] = useState(memory.type);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await updateMemory(memory.id, { content, type });
      setEditing(false);
      onChanged();
    } catch (err) {
      notify(err.message, "error");
    } finally {
      setSaving(false);
    }
  };
  const remove = async () => {
    if (!window.confirm("Delete this memory? LYRA will no longer recall it.")) return;
    try {
      await deleteMemory(memory.id);
      onChanged();
    } catch (err) {
      notify(err.message, "error");
    }
  };

  return (
    <li className="memory-item">
      {editing ? (
        <div className="memory-edit">
          <textarea value={content} onChange={(e) => setContent(e.target.value)} rows={2} maxLength={2000} />
          <div className="row gap-sm">
            <select value={type} onChange={(e) => setType(e.target.value)}>
              {types.map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}
            </select>
            <button className="btn btn-primary btn-sm" onClick={save} disabled={saving || !content.trim()}>Save</button>
            <button className="btn btn-ghost btn-sm" onClick={() => { setEditing(false); setContent(memory.content); }}>Cancel</button>
          </div>
        </div>
      ) : (
        <>
          <div className="memory-content">
            <p>{memory.content}</p>
            <div className="memory-meta">
              <Badge tone="accent">{titleCase(memory.type)}</Badge>
              <span className="muted small">{memory.source} · {timeAgo(memory.updated_at)}</span>
            </div>
          </div>
          <div className="memory-tools">
            <button className="icon-btn" onClick={() => setEditing(true)} aria-label="Edit memory"><Icon name="edit" size={15} /></button>
            <button className="icon-btn" onClick={remove} aria-label="Delete memory"><Icon name="trash" size={15} /></button>
          </div>
        </>
      )}
    </li>
  );
}

export default function MemoryPage() {
  const { openMenu } = useLayout();
  const { notify } = useApp();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [filter, setFilter] = useState("");
  const [newContent, setNewContent] = useState("");
  const [newType, setNewType] = useState("fact");
  const [adding, setAdding] = useState(false);
  const types = useAsync(memoryTypes, []);
  const memories = useAsync(() => listMemories({ q: debounced, type: filter }), [debounced, filter]);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(t);
  }, [query]);

  const add = async (e) => {
    e.preventDefault();
    if (!newContent.trim()) return;
    setAdding(true);
    try {
      await createMemory({ content: newContent.trim(), type: newType });
      setNewContent("");
      notify("Memory saved.", "success");
      memories.reload();
    } catch (err) {
      notify(err.message, "error");
    } finally {
      setAdding(false);
    }
  };

  const typeList = types.data || [];
  return (
    <div className="page">
      <Header title="Memory" onMenu={openMenu} />
      <div className="page-body narrow">
        <PageHeader title="Memory" subtitle="What LYRA remembers about you. It uses these to personalise answers." />
        <Card title="Add a memory" icon="plus">
          <form className="memory-add" onSubmit={add}>
            <input value={newContent} onChange={(e) => setNewContent(e.target.value)} placeholder="e.g. I prefer concise answers" maxLength={2000} />
            <select value={newType} onChange={(e) => setNewType(e.target.value)} aria-label="Memory type">
              {typeList.map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}
            </select>
            <button className="btn btn-primary" disabled={adding || !newContent.trim()}>{adding ? "Saving…" : "Save"}</button>
          </form>
        </Card>

        <div className="toolbar">
          <div className="search">
            <Icon name="search" size={16} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search memories" aria-label="Search memories" />
          </div>
          <div className="chips">
            <button className={`chip ${!filter ? "active" : ""}`} onClick={() => setFilter("")}>All</button>
            {typeList.map((t) => (
              <button key={t} className={`chip ${filter === t ? "active" : ""}`} onClick={() => setFilter(t)}>{titleCase(t)}</button>
            ))}
          </div>
        </div>

        <ErrorBanner error={memories.error} onRetry={memories.reload} />
        {memories.loading && !memories.data ? <Spinner /> : memories.data?.length ? (
          <ul className="memory-list">
            {memories.data.map((m) => <MemoryItem key={m.id} memory={m} types={typeList} onChanged={memories.reload} />)}
          </ul>
        ) : !memories.error && (
          <EmptyState icon="brain" title={debounced || filter ? "No matching memories" : "No memories yet"}>
            LYRA saves useful facts and preferences as you chat, or you can add them above.
          </EmptyState>
        )}
      </div>
    </div>
  );
}
