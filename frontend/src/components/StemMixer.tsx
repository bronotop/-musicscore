import { useEffect, useRef, useState } from "react";
import { fileUrl } from "../api";

interface Props {
  projectId: string;
  stems: string[];
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds)) return "0:00";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0");
  return `${minutes}:${rest}`;
}

export function StemMixer({ projectId, stems }: Props) {
  const refs = useRef<Record<string, HTMLAudioElement | null>>({});
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volumes, setVolumes] = useState<Record<string, number>>({});
  const [muted, setMuted] = useState<Record<string, boolean>>({});
  const [solo, setSolo] = useState<string | null>(null);

  useEffect(() => {
    setPlaying(false);
    setTime(0);
    setDuration(0);
    setVolumes({});
    setMuted({});
    setSolo(null);
  }, [projectId, stems.join(",")]);

  useEffect(() => {
    for (const stem of stems) {
      const audio = refs.current[stem];
      if (!audio) continue;
      audio.volume = volumes[stem] ?? 0.8;
      audio.muted = Boolean(muted[stem]) || (solo !== null && solo !== stem);
    }
  }, [volumes, muted, solo, stems]);

  const toggle = async () => {
    if (playing) {
      stems.forEach((stem) => refs.current[stem]?.pause());
      setPlaying(false);
      return;
    }
    const audios = stems
      .map((stem) => refs.current[stem])
      .filter((audio): audio is HTMLAudioElement => Boolean(audio));
    audios.forEach((audio) => {
      audio.currentTime = time;
    });
    await Promise.all(audios.map((audio) => audio.play().catch(() => undefined)));
    setPlaying(true);
  };

  const seek = (value: number) => {
    setTime(value);
    stems.forEach((stem) => {
      const audio = refs.current[stem];
      if (audio) audio.currentTime = value;
    });
  };

  return (
    <div className="mixer">
      <div className="transport">
        <button className="play" onClick={toggle} disabled={stems.length === 0}>
          {playing ? "暂停" : "播放"}
        </button>
        <span className="time">
          {formatTime(time)} / {formatTime(duration)}
        </span>
        <input
          className="seek"
          type="range"
          min={0}
          max={duration || 1}
          step={0.01}
          value={time}
          onChange={(event) => seek(Number(event.target.value))}
        />
      </div>

      <div className="stem-list">
        {stems.map((stem) => (
          <div className="stem-row" key={stem}>
            <div className="stem-name">{stem}</div>
            <button
              className={muted[stem] ? "chip active" : "chip"}
              onClick={() => setMuted((current) => ({ ...current, [stem]: !current[stem] }))}
              title="静音"
            >
              M
            </button>
            <button
              className={solo === stem ? "chip active" : "chip"}
              onClick={() => setSolo((current) => (current === stem ? null : stem))}
              title="独奏"
            >
              S
            </button>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={volumes[stem] ?? 0.8}
              onChange={(event) =>
                setVolumes((current) => ({ ...current, [stem]: Number(event.target.value) }))
              }
            />
            <audio
              ref={(element) => {
                refs.current[stem] = element;
              }}
              src={fileUrl(projectId, `stems/${stem}.wav`)}
              preload="auto"
              onTimeUpdate={
                stem === stems[0]
                  ? (event) => setTime(event.currentTarget.currentTime)
                  : undefined
              }
              onLoadedMetadata={
                stem === stems[0]
                  ? (event) => setDuration(event.currentTarget.duration)
                  : undefined
              }
              onEnded={stem === stems[0] ? () => setPlaying(false) : undefined}
            />
          </div>
        ))}
      </div>
      {stems.length === 0 && <div className="placeholder">还没有分轨文件</div>}
    </div>
  );
}
