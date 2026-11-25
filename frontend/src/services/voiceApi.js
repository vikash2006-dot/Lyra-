import { apiData } from "./api";

export const voiceStatus = () => apiData("/api/voice/status");
export const listVoices = () => apiData("/api/voice/voices");
export const speak = (text, voice) => apiData("/api/voice/speak", { method: "POST", body: { text, voice } });

export function transcribe(wavBlob) {
  const form = new FormData();
  form.append("audio", wavBlob, "speech.wav");
  return apiData("/api/voice/transcribe", { method: "POST", form });
}

export function voiceCommand(wavBlob, { sessionId, speak: shouldSpeak = true, voice } = {}) {
  const form = new FormData();
  form.append("audio", wavBlob, "speech.wav");
  if (sessionId) form.append("session_id", sessionId);
  form.append("speak", String(shouldSpeak));
  if (voice) form.append("voice", voice);
  return apiData("/api/voice/command", { method: "POST", form, timeout: 180_000 });
}
