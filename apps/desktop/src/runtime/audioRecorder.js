/**
 * High-performance browser audio recorder that captures 16kHz 16-bit mono PCM WAV
 * for direct ingestion by Cortex backend /audio_chat and VoiceTranscriber.
 */

export class AudioRecorder {
  constructor() {
    this.audioCtx = null;
    this.mediaStream = null;
    this.scriptNode = null;
    this.sourceNode = null;
    this.audioData = [];
    this.isRecording = false;
  }

  async start(deviceId = null) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    this.audioCtx = new AudioContextClass({ sampleRate: 16000 });
    if (this.audioCtx.state === "suspended") {
      await this.audioCtx.resume();
    }

    const constraints = {
      audio: deviceId && deviceId !== "default"
        ? { deviceId: { exact: deviceId }, echoCancellation: true, noiseSuppression: true }
        : { echoCancellation: true, noiseSuppression: true },
    };

    this.mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
    this.sourceNode = this.audioCtx.createMediaStreamSource(this.mediaStream);

    // 4096 buffer size at 16kHz = ~256ms chunk size
    this.scriptNode = this.audioCtx.createScriptProcessor(4096, 1, 1);
    this.audioData = [];

    this.scriptNode.onaudioprocess = (e) => {
      if (!this.isRecording) return;
      const channel = e.inputBuffer.getChannelData(0);
      this.audioData.push(new Float32Array(channel));
    };

    this.sourceNode.connect(this.scriptNode);
    this.scriptNode.connect(this.audioCtx.destination);
    this.isRecording = true;

    return this.mediaStream;
  }

  async stop() {
    this.isRecording = false;

    if (this.sourceNode && this.scriptNode) {
      try {
        this.sourceNode.disconnect();
        this.scriptNode.disconnect();
      } catch {}
    }

    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => track.stop());
    }

    const sampleRate = this.audioCtx ? this.audioCtx.sampleRate : 16000;
    if (this.audioCtx && this.audioCtx.state !== "closed") {
      try {
        await this.audioCtx.close();
      } catch {}
    }

    // Merge Float32Array chunks
    let totalLength = 0;
    for (const chunk of this.audioData) {
      totalLength += chunk.length;
    }
    const merged = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of this.audioData) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }

    // Encode to 16-bit PCM WAV Blob
    return encodeWav(merged, sampleRate);
  }
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  // RIFF identifier
  writeString(view, 0, "RIFF");
  // RIFF chunk length
  view.setUint32(4, 36 + samples.length * 2, true);
  // RIFF type
  writeString(view, 8, "WAVE");
  // format chunk identifier
  writeString(view, 12, "fmt ");
  // format chunk length
  view.setUint32(16, 16, true);
  // sample format (1 = PCM)
  view.setUint16(20, 1, true);
  // channel count (1 = mono)
  view.setUint16(22, 1, true);
  // sample rate
  view.setUint32(24, sampleRate, true);
  // byte rate (sample rate * block align)
  view.setUint32(28, sampleRate * 2, true);
  // block align (channel count * bytes per sample)
  view.setUint16(32, 2, true);
  // bits per sample
  view.setUint16(34, 16, true);
  // data chunk identifier
  writeString(view, 36, "data");
  // data chunk length
  view.setUint32(40, samples.length * 2, true);

  // Write PCM samples
  let index = 44;
  for (let i = 0; i < samples.length; i++, index += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(index, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }

  return new Blob([buffer], { type: "audio/wav" });
}

function writeString(view, offset, string) {
  for (let i = 0; i < string.length; i++) {
    view.setUint8(offset + i, string.charCodeAt(i));
  }
}
