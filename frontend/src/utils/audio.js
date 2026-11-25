/**
 * Microphone capture for LYRA voice.
 * Records mono audio, detects end of speech by silence, and encodes 16 kHz 16-bit PCM WAV —
 * the format the backend's speech recognizer accepts without extra codecs.
 */

const TARGET_RATE = 16000;

export function encodeWav(samples, sampleRate = TARGET_RATE) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const write = (offset, str) => [...str].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  write(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  write(8, "WAVE");
  write(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i += 1, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

function downsample(input, fromRate, toRate) {
  if (fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j += 1) sum += input[j];
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}

export class MicRecorder {
  /**
   * @param {object} opts
   * @param {(level:number)=>void} [opts.onLevel] live input level 0..1 for visualisation
   * @param {number} [opts.silenceMs] stop after this much silence following speech
   * @param {number} [opts.maxMs] hard stop
   * @param {number} [opts.noSpeechMs] give up if no speech starts within this time
   */
  constructor({ onLevel, silenceMs = 1300, maxMs = 15000, noSpeechMs = 8000 } = {}) {
    Object.assign(this, { onLevel, silenceMs, maxMs, noSpeechMs });
    this.chunks = [];
    this.active = false;
  }

  static isSupported() {
    return Boolean(navigator.mediaDevices?.getUserMedia && (window.AudioContext || window.webkitAudioContext));
  }

  /** Resolves with a WAV Blob when speech ends, or null if nothing was said / cancelled. */
  async record() {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const Ctx = window.AudioContext || window.webkitAudioContext;
    this.ctx = new Ctx();
    const source = this.ctx.createMediaStreamSource(this.stream);
    const processor = this.ctx.createScriptProcessor(4096, 1, 1);
    const mute = this.ctx.createGain();
    mute.gain.value = 0;
    source.connect(processor);
    processor.connect(mute);
    mute.connect(this.ctx.destination);
    this.active = true;

    return new Promise((resolve) => {
      const started = performance.now();
      let speechStarted = false;
      let lastVoice = started;
      let noiseFloor = 0.01;

      this._finish = (keep) => {
        if (!this.active) return;
        this.active = false;
        processor.disconnect();
        source.disconnect();
        this.stream.getTracks().forEach((t) => t.stop());
        const rate = this.ctx.sampleRate;
        this.ctx.close();
        this.onLevel?.(0);
        if (!keep || !speechStarted) return resolve(null);
        const total = this.chunks.reduce((n, c) => n + c.length, 0);
        const merged = new Float32Array(total);
        let off = 0;
        for (const c of this.chunks) {
          merged.set(c, off);
          off += c.length;
        }
        resolve(encodeWav(downsample(merged, rate, TARGET_RATE)));
      };

      processor.onaudioprocess = (e) => {
        if (!this.active) return;
        const data = e.inputBuffer.getChannelData(0);
        this.chunks.push(new Float32Array(data));
        let sum = 0;
        for (let i = 0; i < data.length; i += 1) sum += data[i] * data[i];
        const rms = Math.sqrt(sum / data.length);
        this.onLevel?.(Math.min(1, rms * 8));
        const now = performance.now();
        if (!speechStarted) noiseFloor = noiseFloor * 0.95 + rms * 0.05;
        const threshold = Math.max(0.015, noiseFloor * 2.5);
        if (rms > threshold) {
          speechStarted = true;
          lastVoice = now;
        }
        if (speechStarted && now - lastVoice > this.silenceMs) this._finish(true);
        else if (!speechStarted && now - started > this.noSpeechMs) this._finish(false);
        else if (now - started > this.maxMs) this._finish(true);
      };
    });
  }

  /** Stop now and submit what was captured. */
  stop() {
    this._finish?.(true);
  }

  /** Stop now and discard. */
  cancel() {
    this._finish?.(false);
  }
}

/** Plays base64 audio from the backend; returns a controller with stop(). */
export function playBase64Audio(base64, mimeType, { onEnd } = {}) {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: mimeType || "audio/wav" }));
  const audio = new Audio(url);
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    URL.revokeObjectURL(url);
    onEnd?.();
  };
  audio.onended = finish;
  audio.onerror = finish;
  audio.play().catch(finish);
  return {
    stop() {
      audio.pause();
      finish();
    },
  };
}
