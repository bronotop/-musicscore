import { Midi } from "@tonejs/midi";
import { useCallback, useEffect, useRef, useState } from "react";
import { fileUrl } from "../api";
import type { TrackInfo } from "../types";

const MIDI_PREVIEW_SECONDS = 30;
const MAX_MIDI_NOTES = 800;

interface AuditionState {
  index: number;
  mode: "audio" | "midi";
}

function waveformFor(track: TrackInfo): OscillatorType {
  if (track.is_drum) return "square";
  if (track.program >= 32 && track.program <= 39) return "sawtooth";
  if (track.program >= 88) return "sine";
  return "triangle";
}

export function useTrackAudition(projectId: string) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const animationRef = useRef<number | null>(null);
  const generationRef = useRef(0);
  const [active, setActive] = useState<AuditionState | null>(null);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const [error, setError] = useState("");

  const stop = useCallback(() => {
    generationRef.current += 1;
    if (animationRef.current !== null) {
      cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
    }
    const audio = audioRef.current;
    if (audio) {
      audio.onended = null;
      audio.ontimeupdate = null;
      audio.onloadedmetadata = null;
      audio.pause();
      audio.src = "";
      audioRef.current = null;
    }
    const context = contextRef.current;
    if (context) {
      contextRef.current = null;
      void context.close().catch(() => undefined);
    }
    setActive(null);
    setProgress(0);
    setDuration(0);
  }, []);

  useEffect(() => {
    stop();
    setError("");
  }, [projectId, stop]);

  useEffect(() => () => stop(), [stop]);

  const play = useCallback(
    async (index: number, track: TrackInfo) => {
      if (active && active.index === index) {
        stop();
        return;
      }
      stop();
      setError("");

      if (track.audio) {
        const audio = new Audio(fileUrl(projectId, track.audio));
        audio.preload = "auto";
        audioRef.current = audio;
        setActive({ index, mode: "audio" });
        const update = () => {
          setProgress(audio.currentTime);
          if (Number.isFinite(audio.duration)) setDuration(audio.duration);
        };
        audio.ontimeupdate = update;
        audio.onloadedmetadata = update;
        audio.onended = () => stop();
        try {
          await audio.play();
        } catch {
          stop();
          setError("浏览器无法播放该分轨音频");
        }
        return;
      }

      if (!track.midi || track.midi.endsWith("full.mid")) {
        setError("该轨没有独立 MIDI 或音频，无法试听");
        return;
      }

      const generation = generationRef.current;
      try {
        const response = await fetch(fileUrl(projectId, track.midi), {
          cache: "no-store",
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const midi = new Midi(await response.arrayBuffer());
        const notes = midi.tracks.flatMap((item) => item.notes);
        if (!notes.length) throw new Error("MIDI 没有音符");
        if (generation !== generationRef.current) return;

        const start = Math.min(...notes.map((note) => note.time));
        const last = Math.max(...notes.map((note) => note.time + note.duration));
        const previewDuration = Math.max(
          0.5,
          Math.min(MIDI_PREVIEW_SECONDS, last - start),
        );

        const context = new AudioContext();
        contextRef.current = context;
        await context.resume();
        const master = context.createGain();
        master.gain.value = 0.18;
        const compressor = context.createDynamicsCompressor();
        compressor.connect(context.destination);
        master.connect(compressor);

        const base = context.currentTime + 0.08;
        let scheduled = 0;
        for (const note of notes) {
          const offset = note.time - start;
          if (offset < 0 || offset > previewDuration) continue;
          if (scheduled >= MAX_MIDI_NOTES) break;
          scheduled += 1;

          const oscillator = context.createOscillator();
          oscillator.type = waveformFor(track);
          oscillator.frequency.value = 440 * 2 ** ((note.midi - 69) / 12);
          const gain = context.createGain();
          const noteDuration = track.is_drum
            ? Math.min(0.09, Math.max(0.03, note.duration))
            : Math.max(
                0.08,
                Math.min(note.duration, previewDuration - offset),
              );
          const peak = Math.max(0.015, Math.min(0.2, note.velocity * 0.3));
          gain.gain.setValueAtTime(0.0001, base + offset);
          gain.gain.exponentialRampToValueAtTime(peak, base + offset + 0.012);
          gain.gain.exponentialRampToValueAtTime(
            0.0001,
            base + offset + noteDuration,
          );
          oscillator.connect(gain).connect(master);
          oscillator.start(base + offset);
          oscillator.stop(base + offset + noteDuration + 0.03);
        }

        setActive({ index, mode: "midi" });
        setDuration(previewDuration);
        setProgress(0);
        const tick = () => {
          const elapsed = Math.max(0, context.currentTime - base);
          if (elapsed >= previewDuration) {
            stop();
            return;
          }
          setProgress(elapsed);
          animationRef.current = requestAnimationFrame(tick);
        };
        animationRef.current = requestAnimationFrame(tick);
      } catch (exc) {
        stop();
        setError(`MIDI 试听失败：${String(exc)}`);
      }
    },
    [active, projectId, stop],
  );

  return { active, progress, duration, error, play, stop };
}
