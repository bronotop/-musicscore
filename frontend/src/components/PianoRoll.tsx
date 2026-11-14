import { Midi } from "@tonejs/midi";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

type PianoTrack = Midi["tracks"][number];
type PianoNote = PianoTrack["notes"][number];

interface Props {
  projectId: string;
  url: string;
  confidenceUrl?: string;
  onSaved?: () => void;
  initialTrackIndex?: number;
}

interface View {
  width: number;
  height: number;
  left: number;
  right: number;
  top: number;
  bottom: number;
  viewStart: number;
  viewSeconds: number;
  minPitch: number;
  maxPitch: number;
  secondsPerBeat: number;
  pxPerSecond: number;
  rowHeight: number;
}

interface DragNote {
  note: PianoNote;
  originalTime: number;
  originalMidi: number;
  originalDuration: number;
}

interface DragState {
  mode: "move" | "resize";
  notes: DragNote[];
  startTime: number;
  startRawPitch: number;
  songDuration: number;
  snapshotTaken: boolean;
}

interface ConfidenceTrack {
  starts: number[];
  pitches: number[];
  values: number[];
}

const HEIGHT = 380;
const LEFT = 48;
const RIGHT = 16;
const TOP = 20;
const BOTTOM = 24;
const MAX_HISTORY = 80;

function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

function copyBytes(bytes: Uint8Array): Uint8Array {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy;
}

function bytesToMidi(bytes: Uint8Array): Midi {
  const buffer = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(buffer).set(bytes);
  return new Midi(buffer);
}

function confidenceAt(
  track: ConfidenceTrack | undefined,
  midi: number,
  time: number
): number {
  if (!track || track.starts.length === 0) return 1;
  const starts = track.starts;
  let low = 0;
  let high = starts.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (starts[middle] < time) low = middle + 1;
    else high = middle;
  }
  let best = 1;
  let bestDelta = 0.035;
  for (let index = Math.max(0, low - 3); index < Math.min(starts.length, low + 4); index += 1) {
    if (track.pitches[index] !== midi) continue;
    const delta = Math.abs(starts[index] - time);
    if (delta <= bestDelta) {
      bestDelta = delta;
      best = track.values[index];
    }
  }
  return best;
}

export function PianoRoll({
  projectId,
  url,
  confidenceUrl,
  onSaved,
  initialTrackIndex,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewRef = useRef<View | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const historyRef = useRef<Uint8Array[]>([]);
  const redoRef = useRef<Uint8Array[]>([]);
  const velocityEditingRef = useRef(false);

  const [midi, setMidi] = useState<Midi | null>(null);
  const [error, setError] = useState("");
  const [selectedTrack, setSelectedTrack] = useState(0);
  const [selectedNotes, setSelectedNotes] = useState<PianoNote[]>([]);
  const [zoom, setZoom] = useState(2);
  const [viewStart, setViewStart] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState("");
  const [renderTick, setRenderTick] = useState(0);
  const [reloadToken, setReloadToken] = useState(0);
  const [width, setWidth] = useState(800);
  const [historyTick, setHistoryTick] = useState(0);
  const [confidence, setConfidence] = useState<Record<string, ConfidenceTrack>>({});

  const duration = midi?.duration ?? 0;
  const viewSeconds = Math.min(Math.max(duration, 2), Math.max(2, 16 / zoom));
  const maxStart = Math.max(0, duration - viewSeconds);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver(() => {
      setWidth(Math.max(320, element.clientWidth));
    });
    observer.observe(element);
    setWidth(Math.max(320, element.clientWidth));
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    setMidi(null);
    setError("");
    setStatus("");
    setSelectedNotes([]);
    setSelectedTrack(0);
    setViewStart(0);
    setDirty(false);
    historyRef.current = [];
    redoRef.current = [];
    setHistoryTick((tick) => tick + 1);
    fetch(url, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.arrayBuffer();
      })
      .then((buffer) => {
        if (!cancelled) setMidi(new Midi(buffer));
      })
      .catch((exc) => {
        if (!cancelled) setError(String(exc));
      });
    return () => {
      cancelled = true;
    };
  }, [url, reloadToken]);

  useEffect(() => {
    if (!midi || midi.tracks.length === 0 || initialTrackIndex === undefined) {
      return;
    }
    const next = Math.max(
      0,
      Math.min(Math.floor(initialTrackIndex), midi.tracks.length - 1),
    );
    setSelectedTrack(next);
    setSelectedNotes([]);
  }, [midi, initialTrackIndex]);

  useEffect(() => {
    if (!confidenceUrl) {
      setConfidence({});
      return;
    }
    let cancelled = false;
    fetch(confidenceUrl, { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        const tracks: Record<string, ConfidenceTrack> = {};
        for (const track of data.tracks ?? []) {
          const starts: number[] = [];
          const pitches: number[] = [];
          const values: number[] = [];
          for (const note of track.notes ?? []) {
            starts.push(Number(note.start));
            pitches.push(Number(note.pitch));
            values.push(Number(note.confidence ?? 1));
          }
          tracks[String(track.stem).toLowerCase()] = { starts, pitches, values };
        }
        setConfidence(tracks);
      })
      .catch(() => setConfidence({}));
    return () => {
      cancelled = true;
    };
  }, [confidenceUrl]);

  const snapshot = useCallback(() => {
    if (!midi) return;
    historyRef.current.push(copyBytes(midi.toArray()));
    if (historyRef.current.length > MAX_HISTORY) historyRef.current.shift();
    redoRef.current = [];
    setHistoryTick((tick) => tick + 1);
  }, [midi]);

  const restore = useCallback((bytes: Uint8Array) => {
    setMidi(bytesToMidi(bytes));
    setSelectedNotes([]);
    setDirty(true);
    setStatus("");
    setRenderTick((tick) => tick + 1);
    setHistoryTick((tick) => tick + 1);
  }, []);

  const undo = useCallback(() => {
    const bytes = historyRef.current.pop();
    if (!bytes || !midi) return;
    redoRef.current.push(copyBytes(midi.toArray()));
    restore(bytes);
  }, [midi, restore]);

  const redo = useCallback(() => {
    const bytes = redoRef.current.pop();
    if (!bytes || !midi) return;
    historyRef.current.push(copyBytes(midi.toArray()));
    restore(bytes);
  }, [midi, restore]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !midi) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(HEIGHT * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${HEIGHT}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const track = midi.tracks[selectedTrack] ?? null;
    const bpm = midi.header.tempos[0]?.bpm || 120;
    const secondsPerBeat = 60 / bpm;
    const start = clamp(viewStart, 0, maxStart);
    const pitches = track ? track.notes.map((note) => note.midi) : [];
    let minPitch = pitches.length ? Math.min(...pitches) - 6 : 36;
    let maxPitch = pitches.length ? Math.max(...pitches) + 6 : 84;
    if (maxPitch - minPitch < 24) {
      const middle = (minPitch + maxPitch) / 2;
      minPitch = middle - 12;
      maxPitch = middle + 12;
    }
    minPitch = Math.max(21, Math.floor(minPitch));
    maxPitch = Math.min(108, Math.ceil(maxPitch));

    const pxPerSecond = (width - LEFT - RIGHT) / viewSeconds;
    const rowHeight = (HEIGHT - TOP - BOTTOM) / (maxPitch - minPitch);
    const view: View = {
      width,
      height: HEIGHT,
      left: LEFT,
      right: RIGHT,
      top: TOP,
      bottom: BOTTOM,
      viewStart: start,
      viewSeconds,
      minPitch,
      maxPitch,
      secondsPerBeat,
      pxPerSecond,
      rowHeight,
    };
    viewRef.current = view;

    ctx.clearRect(0, 0, width, HEIGHT);
    ctx.fillStyle = "#10141d";
    ctx.fillRect(0, 0, width, HEIGHT);

    for (let pitch = minPitch; pitch <= maxPitch; pitch += 1) {
      const y = HEIGHT - BOTTOM - (pitch - minPitch) * rowHeight;
      ctx.strokeStyle = pitch % 12 === 0 ? "#26324a" : "#171f2c";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(LEFT, y);
      ctx.lineTo(width - RIGHT, y);
      ctx.stroke();
      if (pitch % 12 === 0) {
        ctx.fillStyle = "#6f7b8f";
        ctx.font = "10px system-ui";
        ctx.fillText(`C${Math.floor(pitch / 12) - 1}`, 8, y + 3);
      }
    }

    const viewEnd = start + viewSeconds;
    const firstBeat = Math.max(0, Math.ceil(start / secondsPerBeat));
    const lastBeat = Math.floor(viewEnd / secondsPerBeat);
    for (let beat = firstBeat; beat <= lastBeat; beat += 1) {
      const x = LEFT + (beat * secondsPerBeat - start) * pxPerSecond;
      ctx.strokeStyle = beat % 4 === 0 ? "#2d3c5c" : "#1b2433";
      ctx.beginPath();
      ctx.moveTo(x, TOP);
      ctx.lineTo(x, HEIGHT - BOTTOM);
      ctx.stroke();
    }

    const confidenceTrack = track
      ? confidence[(track.name || "").toLowerCase()]
      : undefined;
    const selectedSet = new Set(selectedNotes);

    if (track) {
      for (const note of track.notes) {
        if (note.time + note.duration < start || note.time > viewEnd) continue;
        const x = LEFT + (note.time - start) * pxPerSecond;
        const noteWidth = Math.max(3, note.duration * pxPerSecond);
        const y = HEIGHT - BOTTOM - (note.midi - minPitch) * rowHeight;
        const isSelected = selectedSet.has(note);
        const value = confidenceAt(confidenceTrack, note.midi, note.time);
        ctx.fillStyle = isSelected
          ? "#ffd166"
          : value < 0.45
            ? "#ff6b6b"
            : value < 0.7
              ? "#ffb454"
              : "#7c9cff";
        ctx.globalAlpha = 0.55 + 0.45 * clamp(note.velocity, 0, 1);
        ctx.fillRect(x, y - 3, noteWidth, 6);
        ctx.globalAlpha = 1;
        if (isSelected) {
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 1.5;
          ctx.strokeRect(x - 1, y - 4, noteWidth + 2, 8);
        }
      }
    }

    ctx.fillStyle = "#8b96a8";
    ctx.font = "11px system-ui";
    const trackName = track ? track.name || track.instrument?.name || "轨道" : "无轨道";
    ctx.fillText(`${trackName} · ${track?.notes.length ?? 0} 音符`, LEFT, 13);
    ctx.fillText(
      `${start.toFixed(2)}s – ${(start + viewSeconds).toFixed(2)}s`,
      Math.max(LEFT, width - RIGHT - 120),
      13
    );
  }, [midi, selectedTrack, selectedNotes, viewStart, viewSeconds, maxStart, width, confidence]);

  useLayoutEffect(() => {
    draw();
  }, [draw, renderTick]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      if (event.ctrlKey) {
        setZoom((current) => clamp(current * (event.deltaY < 0 ? 1.2 : 0.82), 0.5, 16));
      } else {
        setViewStart((current) =>
          clamp(current + (event.deltaY || event.deltaX) * viewSeconds * 0.0015, 0, maxStart)
        );
      }
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [viewSeconds, maxStart]);

  const pointFromEvent = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    const view = viewRef.current;
    if (!canvas || !view) return null;
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    return {
      x,
      y,
      time: view.viewStart + Math.max(0, x - view.left) / view.pxPerSecond,
      rawPitch: view.minPitch + (view.height - view.bottom - y) / view.rowHeight,
    };
  };

  const hitNote = (track: PianoTrack, x: number, y: number, view: View): PianoNote | null => {
    for (let index = track.notes.length - 1; index >= 0; index -= 1) {
      const note = track.notes[index];
      const noteX = view.left + (note.time - view.viewStart) * view.pxPerSecond;
      const noteWidth = Math.max(3, note.duration * view.pxPerSecond);
      const noteY = view.height - view.bottom - (note.midi - view.minPitch) * view.rowHeight;
      if (x >= noteX - 2 && x <= noteX + noteWidth + 2 && y >= noteY - 5 && y <= noteY + 5) {
        return note;
      }
    }
    return null;
  };

  const snapTime = (time: number) => {
    const view = viewRef.current;
    const step = (view?.secondsPerBeat ?? 0.5) / 4;
    return Math.max(0, Math.round(time / step) * step);
  };

  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!midi) return;
    const canvas = canvasRef.current;
    const view = viewRef.current;
    const point = pointFromEvent(event);
    if (!canvas || !view || !point) return;
    const track = midi.tracks[selectedTrack];
    if (!track) return;
    canvas.focus();
    canvas.setPointerCapture(event.pointerId);
    const note = hitNote(track, point.x, point.y, view);
    const additive = event.shiftKey || event.metaKey || event.ctrlKey;

    if (!note) {
      if (!additive) setSelectedNotes([]);
      dragRef.current = null;
      return;
    }

    let nextSelection = selectedNotes;
    if (additive) {
      nextSelection = selectedNotes.includes(note)
        ? selectedNotes.filter((candidate) => candidate !== note)
        : [...selectedNotes, note];
    } else if (!selectedNotes.includes(note)) {
      nextSelection = [note];
    }
    setSelectedNotes(nextSelection);
    if (!nextSelection.includes(note)) {
      dragRef.current = null;
      return;
    }

    const noteX = view.left + (note.time - view.viewStart) * view.pxPerSecond;
    const noteWidth = Math.max(3, note.duration * view.pxPerSecond);
    const mode = point.x > noteX + noteWidth - 6 ? "resize" : "move";
    dragRef.current = {
      mode,
      notes: nextSelection.map((candidate) => ({
        note: candidate,
        originalTime: candidate.time,
        originalMidi: candidate.midi,
        originalDuration: candidate.duration,
      })),
      startTime: point.time,
      startRawPitch: point.rawPitch,
      songDuration: midi.duration,
      snapshotTaken: false,
    };
  };

  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!midi) return;
    const canvas = canvasRef.current;
    const view = viewRef.current;
    const point = pointFromEvent(event);
    if (!canvas || !view || !point) return;

    if (!dragRef.current) {
      const track = midi.tracks[selectedTrack];
      const note = track ? hitNote(track, point.x, point.y, view) : null;
      if (!note) {
        canvas.style.cursor = "crosshair";
      } else {
        const noteX = view.left + (note.time - view.viewStart) * view.pxPerSecond;
        const noteWidth = Math.max(3, note.duration * view.pxPerSecond);
        canvas.style.cursor = point.x > noteX + noteWidth - 6 ? "ew-resize" : "move";
      }
      return;
    }

    event.preventDefault();
    const drag = dragRef.current;
    const viewNow = viewRef.current;
    if (!viewNow) return;
    const step = viewNow.secondsPerBeat / 4;

    if (!drag.snapshotTaken) {
      snapshot();
      drag.snapshotTaken = true;
    }

    if (drag.mode === "move") {
      const rawDelta = point.time - drag.startTime;
      const groupDelta = Math.round(rawDelta / step) * step;
      const earliest = Math.min(...drag.notes.map((item) => item.originalTime));
      const latest = Math.max(
        ...drag.notes.map((item) => item.originalTime + item.originalDuration)
      );
      const delta = clamp(groupDelta, -earliest, Math.max(0, drag.songDuration - latest));
      const pitchDelta = Math.round(point.rawPitch - drag.startRawPitch);
      for (const item of drag.notes) {
        item.note.time = Math.max(0, item.originalTime + delta);
        item.note.midi = clamp(item.originalMidi + pitchDelta, 21, 108);
      }
    } else {
      const rawDelta = point.time - drag.startTime;
      const durationDelta = Math.round(rawDelta / step) * step;
      for (const item of drag.notes) {
        item.note.duration = Math.max(
          step,
          Math.round((item.originalDuration + durationDelta) / step) * step
        );
      }
    }
    setDirty(true);
    setRenderTick((tick) => tick + 1);
  };

  const endDrag = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (canvas?.hasPointerCapture(event.pointerId)) {
      canvas.releasePointerCapture(event.pointerId);
    }
    dragRef.current = null;
  };

  const onDoubleClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (!midi) return;
    const view = viewRef.current;
    const track = midi.tracks[selectedTrack];
    if (!view || !track) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    if (hitNote(track, x, y, view)) return;
    const time = snapTime(view.viewStart + Math.max(0, x - view.left) / view.pxPerSecond);
    const pitch = clamp(
      Math.round(view.minPitch + (view.height - view.bottom - y) / view.rowHeight),
      21,
      108
    );
    const step = view.secondsPerBeat / 4;
    snapshot();
    const before = new Set(track.notes);
    track.addNote({ midi: pitch, time, duration: step, velocity: 0.8 });
    const note = track.notes.find((candidate) => !before.has(candidate)) ?? null;
    if (note) setSelectedNotes([note]);
    setDirty(true);
    setRenderTick((tick) => tick + 1);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLCanvasElement>) => {
    if (!midi) return;
    const track = midi.tracks[selectedTrack];
    if (!track) return;
    const meta = event.ctrlKey || event.metaKey;

    if (meta && event.key.toLowerCase() === "z") {
      event.preventDefault();
      if (event.shiftKey) redo();
      else undo();
      return;
    }
    if (meta && event.key.toLowerCase() === "y") {
      event.preventDefault();
      redo();
      return;
    }
    if (meta && event.key.toLowerCase() === "a") {
      event.preventDefault();
      setSelectedNotes([...track.notes]);
      return;
    }
    if (event.key === "Escape") {
      setSelectedNotes([]);
      return;
    }
    if (!selectedNotes.length) return;

    const view = viewRef.current;
    const step = (view?.secondsPerBeat ?? 0.5) / 4;

    if (event.key === "Delete" || event.key === "Backspace") {
      snapshot();
      for (const note of selectedNotes) {
        const index = track.notes.indexOf(note);
        if (index >= 0) track.notes.splice(index, 1);
      }
      setSelectedNotes([]);
      setDirty(true);
      setRenderTick((tick) => tick + 1);
      event.preventDefault();
      return;
    }

    if (event.key.startsWith("Arrow")) {
      snapshot();
      const timeStep = event.shiftKey ? step * 4 : step;
      for (const note of selectedNotes) {
        if (event.key === "ArrowLeft") note.time = Math.max(0, note.time - timeStep);
        if (event.key === "ArrowRight") note.time += timeStep;
        if (event.key === "ArrowUp") note.midi = clamp(note.midi + 1, 21, 108);
        if (event.key === "ArrowDown") note.midi = clamp(note.midi - 1, 21, 108);
      }
      setDirty(true);
      setRenderTick((tick) => tick + 1);
      event.preventDefault();
      return;
    }

    if (event.key === "[" || event.key === "]") {
      snapshot();
      const factor = event.key === "[" ? 0.5 : 2;
      for (const note of selectedNotes) {
        note.duration = Math.max(step, Math.min(8, note.duration * factor));
      }
      setDirty(true);
      setRenderTick((tick) => tick + 1);
      event.preventDefault();
    }
  };

  const beginVelocityEdit = () => {
    if (!velocityEditingRef.current) {
      snapshot();
      velocityEditingRef.current = true;
    }
  };

  const applyVelocity = (value: number) => {
    beginVelocityEdit();
    const velocity = clamp(value, 1, 127) / 127;
    for (const note of selectedNotes) note.velocity = velocity;
    setDirty(true);
    setRenderTick((tick) => tick + 1);
  };

  const endVelocityEdit = () => {
    velocityEditingRef.current = false;
  };

  const save = async () => {
    if (!midi || !dirty) return;
    setSaving(true);
    setError("");
    setStatus("保存中…");
    try {
      const bytes = midi.toArray();
      const buffer = new ArrayBuffer(bytes.byteLength);
      new Uint8Array(buffer).set(bytes);
      const response = await fetch(
        `/api/projects/${projectId}/midi/final/full.mid`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/octet-stream" },
          body: new Blob([buffer], { type: "application/octet-stream" }),
        }
      );
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      setDirty(false);
      setStatus(`已保存 ${data.notes} 个音符，正在重绘乐谱…`);
      const render = await fetch(`/api/projects/${projectId}/render`, {
        method: "POST",
      });
      if (!render.ok) throw new Error(await render.text());
      onSaved?.();
    } catch (exc) {
      setError(String(exc));
      setStatus("");
    } finally {
      setSaving(false);
    }
  };

  const revert = () => {
    historyRef.current = [];
    redoRef.current = [];
    setHistoryTick((tick) => tick + 1);
    setReloadToken((token) => token + 1);
    setDirty(false);
    setSelectedNotes([]);
    setStatus("");
  };

  const track = midi?.tracks[selectedTrack];
  const selectedVelocity = selectedNotes.length
    ? Math.round((selectedNotes[0].velocity ?? 0.8) * 127)
    : 80;
  const selectedPitches = selectedNotes.map((note) => note.midi);
  const hasConfidence = Object.keys(confidence).length > 0;

  return (
    <div className="pianoroll">
      <div className="pianoroll-toolbar">
        {midi?.tracks.map((candidate, index) => (
          <button
            key={index}
            className={selectedTrack === index ? "chip active" : "chip"}
            onClick={() => {
              setSelectedTrack(index);
              setSelectedNotes([]);
            }}
          >
            {candidate.name || candidate.instrument?.name || `轨道 ${index + 1}`}
          </button>
        ))}
        {!midi && !error && <span className="muted">加载 MIDI…</span>}
        <div className="pianoroll-controls">
          <button className="chip" onClick={() => setZoom((z) => clamp(z / 1.3, 0.5, 16))}>
            −
          </button>
          <span className="muted">{viewSeconds.toFixed(1)}s 视窗</span>
          <button className="chip" onClick={() => setZoom((z) => clamp(z * 1.3, 0.5, 16))}>
            +
          </button>
          <input
            className="seek"
            type="range"
            min={0}
            max={Math.max(maxStart, 0.01)}
            step={0.01}
            value={Math.min(viewStart, maxStart)}
            onChange={(event) => setViewStart(Number(event.target.value))}
          />
          <button
            className="chip"
            onClick={undo}
            disabled={historyRef.current.length === 0}
            title="Ctrl+Z"
          >
            撤销
          </button>
          <button
            className="chip"
            onClick={redo}
            disabled={redoRef.current.length === 0}
            title="Ctrl+Shift+Z / Ctrl+Y"
          >
            重做
          </button>
          <button className="primary compact" onClick={save} disabled={!dirty || saving}>
            {saving ? "保存中…" : "保存并重绘乐谱"}
          </button>
          <button className="chip" onClick={revert} disabled={!dirty || saving}>
            放弃修改
          </button>
        </div>
      </div>

      <div className="pianoroll-canvas" ref={containerRef}>
        {error ? (
          <div className="error">{error}</div>
        ) : (
          <canvas
            ref={canvasRef}
            tabIndex={0}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            onDoubleClick={onDoubleClick}
            onKeyDown={onKeyDown}
          />
        )}
      </div>

      {selectedNotes.length > 0 && (
        <div className="pianoroll-toolbar velocity-row">
          <span className="muted">
            已选 {selectedNotes.length} 音符 · MIDI {Math.min(...selectedPitches)}–
            {Math.max(...selectedPitches)}
          </span>
          <label className="velocity-control">
            力度 {selectedVelocity}
            <input
              type="range"
              min={1}
              max={127}
              step={1}
              value={selectedVelocity}
              onPointerDown={beginVelocityEdit}
              onPointerUp={endVelocityEdit}
              onPointerCancel={endVelocityEdit}
              onBlur={endVelocityEdit}
              onChange={(event) => applyVelocity(Number(event.target.value))}
            />
          </label>
        </div>
      )}

      <div className="pianoroll-hint">
        双击空白添加 · 点击/Shift+点击多选 · 拖动移动 · 拖右边缘改时值 ·
        方向键微调（Shift 加大步长）· [ ] 改时值 · Delete 删除 · Ctrl+Z/Y 撤销/重做 ·
        Ctrl+A 全选 · Ctrl+滚轮缩放 · 滚轮横向滚动
      </div>
      {hasConfidence && (
        <div className="pianoroll-hint">
          音符颜色：蓝色 = 模型高置信，橙色 &lt; 0.7，红色 &lt; 0.45
        </div>
      )}
      {status && <div className="pianoroll-status">{status}</div>}
      {error && <div className="error">{error}</div>}
      {track && <div className="muted">{track.notes.length} 个音符</div>}
      <span hidden>{historyTick}</span>
    </div>
  );
}
