import React, { useEffect, useRef } from "react";

/**
 * Performant, audio-reactive waveform / frequency visualizer.
 * Connects to a Web Audio MediaStream (microphone) or HTMLAudioElement (TTS playback).
 * Renders smooth animated bars responding to real-time audio energy and frequencies.
 */
export function AudioVisualizer({
  stream = null,
  audioElement = null,
  isActive = false,
  mode = "listening", // 'listening' | 'speaking' | 'idle'
  barCount = 18,
  height = 24,
}) {
  const canvasRef = useRef(null);
  const audioCtxRef = useRef(null);
  const analyserRef = useRef(null);
  const sourceRef = useRef(null);
  const animFrameRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    if (!isActive || (!stream && !audioElement)) {
      // Resting idle state: draw a calm resting baseline
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (ctx) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "rgba(148, 163, 184, 0.25)";
        const barWidth = 2;
        const spacing = (canvas.width - barCount * barWidth) / (barCount - 1);
        const centerY = canvas.height / 2;
        for (let i = 0; i < barCount; i++) {
          const x = i * (barWidth + spacing);
          ctx.fillRect(x, centerY - 1.5, barWidth, 3);
        }
      }
      return;
    }

    let isCleanedUp = false;

    try {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
        audioCtxRef.current = new AudioContextClass();
      }
      const audioCtx = audioCtxRef.current;
      if (audioCtx.state === "suspended") {
        audioCtx.resume();
      }

      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 64;
      analyser.smoothingTimeConstant = 0.8;
      analyserRef.current = analyser;

      if (stream) {
        sourceRef.current = audioCtx.createMediaStreamSource(stream);
        sourceRef.current.connect(analyser);
      } else if (audioElement) {
        try {
          sourceRef.current = audioCtx.createMediaElementSource(audioElement);
          sourceRef.current.connect(analyser);
          analyser.connect(audioCtx.destination);
        } catch {
          // In case element source is already connected
        }
      }

      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      const render = () => {
        if (isCleanedUp) return;
        analyser.getByteFrequencyData(dataArray);

        ctx.clearRect(0, 0, canvas.width, canvas.height);

        const barWidth = 2.5;
        const totalBarWidth = barCount * barWidth;
        const spacing = (canvas.width - totalBarWidth) / (barCount + 1);
        const centerY = canvas.height / 2;

        for (let i = 0; i < barCount; i++) {
          // Sample across lower to mid frequencies
          const binIndex = Math.min(bufferLength - 1, Math.floor((i / barCount) * (bufferLength * 0.75)));
          const rawValue = dataArray[binIndex] || 0;
          const normalized = rawValue / 255;
          const barHeight = Math.max(3, normalized * (canvas.height - 4));

          const x = spacing + i * (barWidth + spacing);
          const y = centerY - barHeight / 2;

          // Gradient color depending on mode
          if (mode === "listening") {
            ctx.fillStyle = `rgba(245, 158, 11, ${Math.max(0.4, normalized * 0.9 + 0.2)})`; // Amber
          } else if (mode === "speaking") {
            ctx.fillStyle = `rgba(16, 185, 129, ${Math.max(0.4, normalized * 0.9 + 0.2)})`; // Green
          } else {
            ctx.fillStyle = `rgba(99, 102, 241, ${Math.max(0.4, normalized * 0.9 + 0.2)})`; // Indigo
          }

          // Draw rounded vertical pill
          ctx.beginPath();
          ctx.roundRect(x, y, barWidth, barHeight, 2);
          ctx.fill();
        }

        animFrameRef.current = requestAnimationFrame(render);
      };

      render();
    } catch (err) {
      console.warn("[visualizer] AudioContext initialization notice:", err);
    }

    return () => {
      isCleanedUp = true;
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (sourceRef.current) {
        try {
          sourceRef.current.disconnect();
        } catch {}
      }
    };
  }, [isActive, stream, audioElement, mode, barCount]);

  return (
    <div className="flex items-center justify-center overflow-hidden">
      <canvas
        ref={canvasRef}
        width={barCount * 6}
        height={height}
        className="block"
      />
    </div>
  );
}

export default AudioVisualizer;
