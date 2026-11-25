import { useRef, useState } from "react";
import Markdown from "../components/chat/Markdown";
import Icon from "../components/common/Icon";
import Header from "../components/layout/Header";
import { useLayout } from "../components/layout/Layout";
import { Badge, Card, EmptyState, ErrorBanner, PageHeader, Spinner } from "../components/common/ui";
import { useApp } from "../context/AppContext";
import { useAsync } from "../hooks/useAsync";
import {
  analyzeDocument,
  deleteDocument,
  listDocuments,
  supportedDocumentTypes,
  uploadDocument,
} from "../services/documentApi";
import { formatBytes, timeAgo, titleCase } from "../utils/formatters";

function ResumeResult({ result }) {
  if (!result || typeof result !== "object") return <p className="muted small">No details returned.</p>;
  const skills = result.skills_detected || [];
  const projects = result.projects_detected || [];
  const label = (v) => (typeof v === "string" ? v : v?.name || v?.title || JSON.stringify(v));
  return (
    <div className="analysis">
      {result.summary && <p>{result.summary}</p>}
      {skills.length > 0 && (
        <>
          <h4>Skills found</h4>
          <div className="chips">{skills.map((s, i) => <span key={i} className="chip static">{label(s)}</span>)}</div>
        </>
      )}
      {projects.length > 0 && (
        <>
          <h4>Projects</h4>
          <ul>{projects.map((p, i) => <li key={i}>{label(p)}</li>)}</ul>
        </>
      )}
      {!skills.length && !projects.length && <p className="muted small">No skills or projects were detected.</p>}
      <p className="muted small">Detected skills are added to your learning profile as evidence.</p>
    </div>
  );
}

function DocumentItem({ doc, onChanged }) {
  const { notify } = useApp();
  const [busy, setBusy] = useState(null);
  const [question, setQuestion] = useState("");
  const run = async (mode) => {
    setBusy(mode);
    try {
      await analyzeDocument(doc.id, mode, mode === "summary" ? question : undefined);
      onChanged();
    } catch (err) {
      notify(err.message, "error");
    } finally {
      setBusy(null);
    }
  };
  const remove = async () => {
    if (!window.confirm(`Delete ${doc.filename}?`)) return;
    try {
      await deleteDocument(doc.id);
      onChanged();
    } catch (err) {
      notify(err.message, "error");
    }
  };
  const a = doc.analysis;
  return (
    <li className="doc-item">
      <div className="doc-head">
        <div className="doc-icon"><Icon name="file" size={18} /></div>
        <div className="doc-info">
          <strong>{doc.filename}</strong>
          <span className="muted small">{formatBytes(doc.size_bytes)} · uploaded {timeAgo(doc.created_at)}</span>
        </div>
        <button className="icon-btn" onClick={remove} aria-label="Delete document"><Icon name="trash" size={15} /></button>
      </div>
      <div className="doc-actions">
        <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Optional: ask something about this document" maxLength={2000} />
        <button className="btn btn-primary btn-sm" onClick={() => run("summary")} disabled={!!busy}>
          {busy === "summary" ? <><Spinner size={12} /> Analyzing…</> : question.trim() ? "Ask" : "Summarize"}
        </button>
        <button className="btn btn-ghost btn-sm" onClick={() => run("resume")} disabled={!!busy}>
          {busy === "resume" ? <><Spinner size={12} /> Reading…</> : "Analyze as resume"}
        </button>
      </div>
      {a && (
        <div className="doc-analysis">
          <div className="row gap-sm"><Badge tone="accent">{titleCase(a.mode)}</Badge><span className="muted small">{timeAgo(a.analyzed_at)}</span></div>
          {a.mode === "summary" ? <Markdown text={a.summary} /> : <ResumeResult result={a.result} />}
        </div>
      )}
    </li>
  );
}

export default function DocumentsPage() {
  const { openMenu } = useLayout();
  const { notify } = useApp();
  const docs = useAsync(listDocuments, []);
  const types = useAsync(supportedDocumentTypes, []);
  const [uploading, setUploading] = useState(false);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef(null);
  const accept = types.data?.extensions?.join(",");
  const maxBytes = types.data?.max_bytes;

  const upload = async (files) => {
    const list = [...(files || [])];
    if (!list.length) return;
    setUploading(true);
    for (const file of list) {
      if (maxBytes && file.size > maxBytes) {
        notify(`${file.name} is larger than ${formatBytes(maxBytes)}.`, "error");
        continue;
      }
      try {
        await uploadDocument(file);
        notify(`Uploaded ${file.name}`, "success");
      } catch (err) {
        notify(`${file.name}: ${err.message}`, "error");
      }
    }
    setUploading(false);
    if (inputRef.current) inputRef.current.value = "";
    docs.reload();
  };

  return (
    <div className="page">
      <Header title="Documents" onMenu={openMenu} />
      <div className="page-body narrow">
        <PageHeader title="Documents" subtitle="Upload notes, code or your resume. LYRA analyzes them on the backend." />
        <Card>
          <div
            className={`dropzone ${drag ? "drag" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files); }}
            onClick={() => inputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
          >
            {uploading ? <Spinner size={22} /> : <Icon name="upload" size={22} />}
            <p><strong>{uploading ? "Uploading…" : "Drop files here or click to upload"}</strong></p>
            <p className="muted small">
              {types.data ? `${types.data.extensions.join(" ")} · up to ${formatBytes(maxBytes)}` : "Loading supported types…"}
            </p>
            <input ref={inputRef} type="file" hidden multiple accept={accept} onChange={(e) => upload(e.target.files)} />
          </div>
        </Card>
        <ErrorBanner error={docs.error} onRetry={docs.reload} />
        {docs.loading && !docs.data ? <Spinner /> : docs.data?.length ? (
          <ul className="doc-list">{docs.data.map((d) => <DocumentItem key={d.id} doc={d} onChanged={docs.reload} />)}</ul>
        ) : !docs.error && <EmptyState icon="file" title="No documents yet">Uploaded files stay on your machine in the backend's storage folder.</EmptyState>}
      </div>
    </div>
  );
}
