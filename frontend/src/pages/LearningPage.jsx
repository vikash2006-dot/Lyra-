import { useEffect, useState } from "react";
import Header from "../components/layout/Header";
import { useLayout } from "../components/layout/Layout";
import { Badge, Card, ErrorBanner, PageHeader, Spinner } from "../components/common/ui";
import { useApp } from "../context/AppContext";
import { useAsync } from "../hooks/useAsync";
import {
  addSkill,
  completeLearningTask,
  createPlan,
  generatePractice,
  getGaps,
  getPlan,
  getProfile,
  getProgress,
  getProject,
  getResources,
  getSkills,
  updateProfile,
} from "../services/learningApi";
import { titleCase } from "../utils/formatters";

const LEVELS = ["beginner", "elementary", "intermediate", "advanced", "expert"];
const STYLES = ["hands-on", "visual", "reading", "video", "project-based"];

function ProfileCard({ profile, roles, onSaved }) {
  const { notify } = useApp();
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (profile) {
      setForm({
        name: profile.name || "",
        target_role: profile.target_role || "",
        career_goal: profile.career_goal || "",
        weekly_learning_hours: profile.weekly_learning_hours ?? 8,
        preferred_learning_style: profile.preferred_learning_style || "hands-on",
      });
    }
  }, [profile]);
  if (!form) return <Card title="Profile" icon="target"><Spinner /></Card>;
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await updateProfile({ ...form, weekly_learning_hours: Number(form.weekly_learning_hours) || 0 });
      notify("Learning profile saved.", "success");
      onSaved();
    } catch (err) {
      notify(err.message, "error");
    } finally {
      setSaving(false);
    }
  };
  return (
    <Card title="Learner profile" icon="target">
      <form className="form-grid" onSubmit={save}>
        <label>Name<input value={form.name} onChange={set("name")} maxLength={120} /></label>
        <label>Target role
          <input list="roles" value={form.target_role} onChange={set("target_role")} placeholder="e.g. Backend Developer" maxLength={120} />
          <datalist id="roles">{roles.map((r) => <option key={r} value={r} />)}</datalist>
        </label>
        <label className="span-2">Career goal<input value={form.career_goal} onChange={set("career_goal")} maxLength={500} /></label>
        <label>Hours per week<input type="number" min="0" max="100" value={form.weekly_learning_hours} onChange={set("weekly_learning_hours")} /></label>
        <label>Learning style
          <select value={form.preferred_learning_style} onChange={set("preferred_learning_style")}>
            {[...new Set([form.preferred_learning_style, ...STYLES])].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
          </select>
        </label>
        <div className="span-2 row end"><button className="btn btn-primary" disabled={saving}>{saving ? "Saving…" : "Save profile"}</button></div>
      </form>
      {profile?.missing_intake_fields?.length > 0 && (
        <p className="muted small">Still missing: {profile.missing_intake_fields.map(titleCase).join(", ")}</p>
      )}
    </Card>
  );
}

function SkillsCard({ skills, onChanged }) {
  const { notify } = useApp();
  const [skill, setSkill] = useState("");
  const [level, setLevel] = useState("beginner");
  const add = async (e) => {
    e.preventDefault();
    if (!skill.trim()) return;
    try {
      await addSkill(skill.trim(), level);
      setSkill("");
      onChanged();
    } catch (err) {
      notify(err.message, "error");
    }
  };
  return (
    <Card title="Skills" icon="sparkle">
      <form className="inline-form" onSubmit={add}>
        <input value={skill} onChange={(e) => setSkill(e.target.value)} placeholder="Add a skill you have" maxLength={120} />
        <select value={level} onChange={(e) => setLevel(e.target.value)}>{LEVELS.map((l) => <option key={l} value={l}>{titleCase(l)}</option>)}</select>
        <button className="btn btn-primary btn-sm" disabled={!skill.trim()}>Add</button>
      </form>
      {!skills ? <Spinner /> : skills.skills.length === 0 ? <p className="muted small">No skills recorded yet.</p> : (
        <ul className="skill-list">
          {skills.skills.map((s) => {
            const mastery = s.mastery?.mastery_score;
            return (
              <li key={s.skill}>
                <span>{s.skill}</span>
                <Badge tone="accent">{titleCase(s.assessed_level || s.self_reported_level || "beginner")}</Badge>
                {mastery != null && (
                  <span className="meter" title={`Mastery ${Math.round(mastery * 100)}%`}><i style={{ width: `${Math.round(mastery * 100)}%` }} /></span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function PlanCard({ planData, hasRole, onChanged }) {
  const { notify } = useApp();
  const [weeks, setWeeks] = useState(8);
  const [creating, setCreating] = useState(false);
  const plan = planData?.plan;
  const create = async () => {
    setCreating(true);
    try {
      await createPlan(Number(weeks));
      notify("Learning plan created.", "success");
      onChanged();
    } catch (err) {
      notify(err.message, "error");
    } finally {
      setCreating(false);
    }
  };
  const complete = async (taskId) => {
    try {
      await completeLearningTask(taskId);
      onChanged();
    } catch (err) {
      notify(err.message, "error");
    }
  };
  return (
    <Card
      title="Weekly plan"
      icon="book"
      className="span-2"
      actions={
        <div className="row gap-sm">
          <select value={weeks} onChange={(e) => setWeeks(e.target.value)} aria-label="Plan length">
            {[2, 4, 6, 8, 12].map((w) => <option key={w} value={w}>{w} weeks</option>)}
          </select>
          <button className="btn btn-primary btn-sm" onClick={create} disabled={creating || !hasRole}>
            {creating ? "Generating…" : plan ? "Regenerate" : "Generate plan"}
          </button>
        </div>
      }
    >
      {!hasRole && <p className="muted small">Set a target role in your profile to generate a plan.</p>}
      {plan ? (
        <>
          {plan.objectives?.length > 0 && (
            <div className="objectives"><h4>Objectives</h4><ul>{plan.objectives.slice(0, 6).map((o, i) => <li key={i}>{o}</li>)}</ul></div>
          )}
          <div className="weeks">
            {plan.weeks.slice(0, 4).map((w) => (
              <details key={w.week_number} open={w.week_number === plan.weeks[0].week_number}>
                <summary><strong>Week {w.week_number}</strong> · {w.theme}</summary>
                {w.milestone && <p className="muted small">Milestone: {w.milestone}</p>}
                <div className="days">
                  {w.days.map((d) => (
                    <div key={d.day} className="day">
                      <h5>{d.day} <span className="muted small">{d.total_minutes} min</span></h5>
                      <ul>
                        {d.tasks.map((t) => (
                          <li key={t.task_id} className={t.completed ? "done" : ""}>
                            <button className="check" onClick={() => !t.completed && complete(t.task_id)} aria-label={t.completed ? "Completed" : "Mark complete"} disabled={t.completed}>
                              {t.completed ? "✓" : ""}
                            </button>
                            <span>{t.title}</span>
                            <span className="muted small">{t.duration_minutes}m</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </details>
            ))}
            {plan.weeks.length > 4 && <p className="muted small">+ {plan.weeks.length - 4} more weeks</p>}
          </div>
        </>
      ) : hasRole && <p className="muted small">No active plan yet.</p>}
    </Card>
  );
}

function ExtrasCard({ hasRole }) {
  const { notify } = useApp();
  const [practice, setPractice] = useState(null);
  const [project, setProject] = useState(null);
  const [resSkill, setResSkill] = useState("");
  const [resources, setResources] = useState(null);
  const [busy, setBusy] = useState(null);
  const run = async (key, fn, setter) => {
    setBusy(key);
    try {
      setter(await fn());
    } catch (err) {
      notify(err.message, "error");
    } finally {
      setBusy(null);
    }
  };
  return (
    <Card title="Practice & projects" icon="sparkle" className="span-2">
      <div className="row gap-sm wrap">
        <button className="btn btn-ghost btn-sm" onClick={() => run("practice", () => generatePractice(), setPractice)} disabled={busy}>
          {busy === "practice" ? "Generating…" : "New practice task"}
        </button>
        <button className="btn btn-ghost btn-sm" onClick={() => run("project", getProject, setProject)} disabled={busy || !hasRole}>
          {busy === "project" ? "Generating…" : "Recommend a project"}
        </button>
        <form className="inline-form" onSubmit={(e) => { e.preventDefault(); if (resSkill.trim()) run("res", () => getResources(resSkill.trim()), setResources); }}>
          <input value={resSkill} onChange={(e) => setResSkill(e.target.value)} placeholder="Resources for a skill…" maxLength={120} />
          <button className="btn btn-ghost btn-sm" disabled={busy || !resSkill.trim()}>{busy === "res" ? "Finding…" : "Find"}</button>
        </form>
      </div>
      {practice && (
        <div className="extra-block">
          <h4>{practice.title} <Badge>{titleCase(practice.level)}</Badge></h4>
          <p>{practice.prompt}</p>
          {practice.starter_code && <pre><code>{practice.starter_code}</code></pre>}
          {practice.hints?.length > 0 && <details><summary>Hints</summary><ul>{practice.hints.map((h, i) => <li key={i}>{h}</li>)}</ul></details>}
        </div>
      )}
      {project && (
        <div className="extra-block">
          <h4>{project.title} <Badge>{titleCase(project.difficulty)}</Badge></h4>
          <p>{project.objective}</p>
          {project.requirements?.length > 0 && <ul>{project.requirements.slice(0, 6).map((r, i) => <li key={i}>{r}</li>)}</ul>}
          {project.technologies?.length > 0 && <div className="chips">{project.technologies.map((t) => <span key={t} className="chip static">{t}</span>)}</div>}
        </div>
      )}
      {resources && (
        <div className="extra-block">
          <h4>Resources</h4>
          {resources.length === 0 ? <p className="muted small">No resources found.</p> : (
            <ul className="simple-list">
              {resources.map((r, i) => (
                <li key={i}>
                  {r.url ? <a href={r.url} target="_blank" rel="noreferrer noopener">{r.title}</a> : r.title}
                  <span className="muted small">{titleCase(r.type)} · {r.estimated_time_minutes}m</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}

export default function LearningPage() {
  const { openMenu } = useLayout();
  const profile = useAsync(getProfile, []);
  const skills = useAsync(getSkills, []);
  const plan = useAsync(getPlan, []);
  const progress = useAsync(getProgress, []);
  const gaps = useAsync(getGaps, []);
  const hasRole = Boolean(profile.data?.target_role);
  const reloadAll = () => { profile.reload(); skills.reload(); plan.reload(); progress.reload(); gaps.reload(); };
  const report = progress.data?.report;

  return (
    <div className="page">
      <Header title="Learning" onMenu={openMenu} />
      <div className="page-body">
        <PageHeader title="Learning" subtitle="Your adaptive learning profile, skill gaps and weekly plan." />
        <ErrorBanner error={profile.error || plan.error} onRetry={reloadAll} />
        <div className="grid">
          <ProfileCard profile={profile.data} roles={skills.data?.target_roles || []} onSaved={reloadAll} />
          <Card title="Progress" icon="activity">
            {!report ? <Spinner /> : (
              <>
                <div className="stats-row">
                  <p className="stat">{report.skills_acquired.length}<span>acquired</span></p>
                  <p className="stat">{report.skills_in_progress.length}<span>in progress</span></p>
                  <p className="stat">{report.remaining_gaps.length}<span>gaps</span></p>
                </div>
                {report.learning_consistency && <p className="muted small">{report.learning_consistency}</p>}
                {report.recommended_next_steps?.length > 0 && (
                  <><h4>Next steps</h4><ul>{report.recommended_next_steps.slice(0, 4).map((s, i) => <li key={i}>{s}</li>)}</ul></>
                )}
              </>
            )}
          </Card>
          <SkillsCard skills={skills.data} onChanged={() => { skills.reload(); gaps.reload(); progress.reload(); }} />
          <Card title="Skill gaps" icon="target">
            {!hasRole ? <p className="muted small">Set a target role to see gaps.</p> : gaps.loading ? <Spinner /> : !gaps.data?.length ? (
              <p className="muted small">No gaps detected for {profile.data.target_role}.</p>
            ) : (
              <ul className="gap-list">
                {gaps.data.slice(0, 8).map((g) => (
                  <li key={g.skill}>
                    <span>{g.skill}</span>
                    <span className="muted small">{titleCase(g.current_level || "none")} → {titleCase(g.required_level)}</span>
                    <Badge tone={g.priority <= 2 ? "warn" : "neutral"}>P{g.priority}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <PlanCard planData={plan.data} hasRole={hasRole} onChanged={() => { plan.reload(); progress.reload(); }} />
          <ExtrasCard hasRole={hasRole} />
        </div>
      </div>
    </div>
  );
}
