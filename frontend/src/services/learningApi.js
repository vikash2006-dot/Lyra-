import { apiData } from "./api";

export const getProfile = () => apiData("/api/learning/profile");
export const updateProfile = (changes) => apiData("/api/learning/profile", { method: "PUT", body: changes });
export const getSkills = () => apiData("/api/learning/skills");
export const addSkill = (skill, level, evidence) =>
  apiData("/api/learning/skills", { method: "POST", body: { skill, level: level || null, evidence: evidence || null } });
export const getGaps = () => apiData("/api/learning/gaps");
export const getPlan = () => apiData("/api/learning/plan");
export const createPlan = (durationWeeks, targetRole) =>
  apiData("/api/learning/plan", {
    method: "POST",
    body: { duration_weeks: durationWeeks, target_role: targetRole || null },
    timeout: 180_000,
  });
export const getProgress = () => apiData("/api/learning/progress");
export const getResources = (skill) => apiData(`/api/learning/resources?skill=${encodeURIComponent(skill)}`);
export const generatePractice = (skill) =>
  apiData("/api/learning/practice", { method: "POST", body: { skill: skill || null } });
export const getProject = () => apiData("/api/learning/project");
export const completeLearningTask = (taskId) =>
  apiData("/api/learning/activity", { method: "POST", body: { action: "complete_task", task_id: taskId } });
