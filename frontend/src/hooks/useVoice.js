import { useCallback, useEffect, useRef, useState } from "react";
import { useApp } from "../context/AppContext";
import { useChat } from "../context/ChatContext";
import { MicRecorder, playBase64Audio } from "../utils/audio";
import { LyraSocket } from "../services/websocket";

/**
 * Voice interaction state machine:
 *   idle -> listening (mic) -> processing (backend STT/LYRA/TTS) -> speaking (playback) -> idle
 * Everything except microphone capture and playback runs on the backend.
 */
export function useVoice({ voice = null, autoSpeak = true, handsFree = false, volume = 1, onSession } = {}) {
  const { notify, upsertTask } = useApp();
  const { activeSessionId, appendMessage, updateMessage, refreshSessions } = useChat();
  const [state, setState] = useState("idle");
  const [detail, setDetail] = useState("");
  const [level, setLevel] = useState(0);
  const [error, setError] = useState(null);
  const [socketStatus, setSocketStatus] = useState("idle");

  const socketRef = useRef(null);
  const recorderRef = useRef(null);
  const playbackRef = useRef(null);
  const audioQueueRef = useRef([]);
  const turnDoneRef = useRef(false);
  const pendingIdRef = useRef(null);
  const stateRef = useRef(state);
  stateRef.current = state;
  const optsRef = useRef({ voice, autoSpeak, handsFree, volume, onSession, activeSessionId });
  optsRef.current = { voice, autoSpeak, handsFree, volume, onSession, activeSessionId };
  const startRef = useRef(null);

  const sendStart = useCallback(() => {
    const o = optsRef.current;
    socketRef.current?.send({ type: "start", session_id: o.activeSessionId, speak: o.autoSpeak, voice: o.voice });
  }, []);

  const toIdle = useCallback((message) => {
    setState("idle");
    setDetail(message || "");
    if (optsRef.current.handsFree && !message) setTimeout(() => startRef.current?.(), 350);
  }, []);

  const fail = useCallback((message) => {
    setError(message);
    setState("error");
    setDetail("");
    if (pendingIdRef.current) {
      updateMessage(pendingIdRef.current, { pending: false, error: message });
      pendingIdRef.current = null;
    }
  }, [updateMessage]);

  // Plays queued clips back-to-back (acknowledgement, then the reply) without overlap.
  const playNext = useCallback(() => {
    if (playbackRef.current) return;
    const next = audioQueueRef.current.shift();
    if (!next) {
      if (turnDoneRef.current && stateRef.current === "speaking") toIdle();
      else if (stateRef.current === "speaking") setState("processing");
      return;
    }
    setState("speaking");
    setDetail("");
    playbackRef.current = playBase64Audio(next.audio_base64, next.mime_type, {
      volume: optsRef.current.volume,
      onEnd: () => {
        playbackRef.current = null;
        if (next.kind === "reply") turnDoneRef.current = true;
        if (stateRef.current === "speaking") playNext();
      },
    });
  }, [toIdle]);

  const stopAudio = useCallback(() => {
    audioQueueRef.current = [];
    playbackRef.current?.stop();
    playbackRef.current = null;
  }, []);

  const markInterrupted = useCallback(() => {
    setState("interrupted");
    setDetail("Interrupted");
    setTimeout(() => {
      if (stateRef.current === "interrupted") {
        setState("idle");
        setDetail("");
      }
    }, 1600);
  }, []);

  const onEvent = useCallback((ev) => {
    switch (ev.type) {
      case "voice_status":
        if (stateRef.current === "speaking") break; // keep "Speaking" while an acknowledgement plays
        if (ev.state === "transcribing") setDetail("Transcribing…");
        else if (ev.state === "thinking") setDetail("Thinking…");
        else if (ev.state === "synthesizing") setDetail("Preparing voice…");
        else if (ev.state === "idle" && stateRef.current === "processing") {
          // Turn finished without (more) audio: e.g. speaking disabled or nothing to say.
          if (!audioQueueRef.current.length && !playbackRef.current) toIdle();
        }
        break;
      case "transcript": {
        const coughed = (ev.audio_events || []).some((e) => e.type === "cough");
        if (!ev.text && !coughed) {
          toIdle("Sorry, I didn't quite catch that — could you say it again?");
          return;
        }
        appendMessage({
          role: "user",
          content: ev.text || "(cough detected)",
          source: "voice",
          audioEvents: ev.audio_events,
          muted: !ev.text,
        });
        pendingIdRef.current = appendMessage({ role: "assistant", content: "", pending: true, source: "voice" });
        break;
      }
      case "acknowledgement":
        if (pendingIdRef.current) updateMessage(pendingIdRef.current, { ack: ev.text });
        break;
      case "task_started":
      case "task_update":
        if (ev.task) {
          upsertTask(ev.task);
          if (pendingIdRef.current) updateMessage(pendingIdRef.current, { task: ev.task });
        }
        break;
      case "response":
        if (pendingIdRef.current) {
          updateMessage(pendingIdRef.current, { content: ev.text, pending: false, task: ev.task || undefined });
          pendingIdRef.current = null;
        }
        if (ev.session_id && ev.session_id !== optsRef.current.activeSessionId) optsRef.current.onSession?.(ev.session_id);
        refreshSessions();
        if (!optsRef.current.autoSpeak) toIdle();
        break;
      case "audio":
        if (stateRef.current !== "processing" && stateRef.current !== "speaking") return; // interrupted meanwhile
        audioQueueRef.current.push(ev);
        playNext();
        break;
      case "cancelled":
        if (pendingIdRef.current) {
          updateMessage(pendingIdRef.current, { pending: false, content: "Stopped.", stopped: true });
          pendingIdRef.current = null;
        }
        break;
      case "error":
        fail(ev.error?.message || "Voice request failed.");
        break;
      default:
        break;
    }
  }, [appendMessage, fail, playNext, refreshSessions, toIdle, updateMessage, upsertTask]);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    const socket = new LyraSocket("/ws/voice", {
      onEvent: (e) => onEventRef.current(e),
      onStatus: (s) => {
        setSocketStatus(s);
        if (s === "open") sendStart();
        else if (s !== "connecting" && ["processing"].includes(stateRef.current)) {
          setError("Voice connection lost.");
          setState("error");
        }
      },
    });
    socketRef.current = socket;
    socket.connect();
    return () => {
      recorderRef.current?.cancel();
      audioQueueRef.current = [];
      playbackRef.current?.stop();
      socket.close();
    };
  }, [sendStart]);

  // Keep the backend voice session in sync with the chat the user is looking at.
  useEffect(() => {
    if (socketRef.current?.isOpen) sendStart();
  }, [activeSessionId, autoSpeak, voice, sendStart]);

  const start = useCallback(async () => {
    if (!MicRecorder.isSupported()) {
      fail("This browser does not support microphone capture.");
      return;
    }
    if (!socketRef.current?.isOpen) {
      fail("Voice service is not connected to the backend.");
      return;
    }
    if (stateRef.current === "listening" || stateRef.current === "processing") return;
    setError(null);
    setDetail("");
    turnDoneRef.current = false;
    audioQueueRef.current = [];
    const recorder = new MicRecorder({ onLevel: setLevel });
    recorderRef.current = recorder;
    setState("listening");
    let wav;
    try {
      wav = await recorder.record();
    } catch (err) {
      recorderRef.current = null;
      const denied = err?.name === "NotAllowedError" || err?.name === "SecurityError";
      fail(denied ? "Microphone permission was denied. Allow it in your browser settings." :
        "Could not access the microphone.");
      return;
    }
    recorderRef.current = null;
    if (!wav) {
      if (stateRef.current === "listening") {
        setState("idle");
        setDetail("No speech detected.");
      }
      return;
    }
    setState("processing");
    setDetail("Sending…");
    const sent = socketRef.current?.send(await wav.arrayBuffer());
    if (!sent) fail("Voice service disconnected.");
  }, [fail]);
  startRef.current = start;

  /** Primary button behaviour: start, or finish speaking early, or interrupt LYRA. */
  const toggle = useCallback(() => {
    const s = stateRef.current;
    if (s === "idle" || s === "error" || s === "interrupted") return start();
    if (s === "listening") return recorderRef.current?.stop();
    if (s === "processing" || s === "speaking") {
      socketRef.current?.send({ type: "interrupt" });
      stopAudio();
      markInterrupted();
    }
    return undefined;
  }, [start, stopAudio, markInterrupted]);

  const cancel = useCallback(() => {
    const s = stateRef.current;
    recorderRef.current?.cancel();
    if (s === "processing" || s === "speaking") socketRef.current?.send({ type: "interrupt" });
    stopAudio();
    if (s === "processing" || s === "speaking") markInterrupted();
    else {
      setState("idle");
      setDetail("");
    }
  }, [stopAudio, markInterrupted]);

  useEffect(() => {
    if (error) notify(error, "error");
  }, [error, notify]);

  return { state, detail, level, error, toggle, cancel, socketStatus, connected: socketStatus === "open" };
}
