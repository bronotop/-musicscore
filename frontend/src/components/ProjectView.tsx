import { useEffect, useState } from "react";
import { fileUrl } from "../api";
import type { ProjectDetail } from "../types";
import { LogView } from "./LogView";
import { PianoRoll } from "./PianoRoll";
import { ScoreView } from "./ScoreView";
import { StemMixer } from "./StemMixer";
import { TrackManager } from "./TrackManager";

const STAGES = ["ingest", "analyze", "separate", "transcribe", "assemble", "notate"];
const STAGE_LABELS: Record<string, string> = {
  ingest: "解码",
  analyze: "节拍/调性",
  separate: "音源分离",
  transcribe: "分轨转录",
  assemble: "量化合并",
  notate: "生成乐谱",
};

const STATUS_LABELS: Record<string, string> = {
  idle: "未开始",
  starting: "启动中",
  running: "处理中",
  done: "完成",
  error: "失败",
};

interface Props {
  detail: ProjectDetail;
  onRun: (preset: string, force: boolean) => Promise<void>;
  onRefresh?: () => Promise<void> | void;
}

type Tab = "mix" | "tracks" | "midi" | "score" | "log";

export function ProjectView({ detail, onRun, onRefresh }: Props) {
  const [tab, setTab] = useState<Tab>("mix");
  const [preset, setPreset] = useState(detail.project.preset || "fast");
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [focusTrack, setFocusTrack] = useState<number | null>(null);

  const projectId = detail.project.project_id;
  const job = detail.job;
  const files = detail.files;
  const fullMidi = files.find((file) => file.endsWith("midi/final/full.mid"));
  const musicxml = files.find((file) => file.endsWith("score/full.musicxml"));
  const pdf =
    files.find((file) => file === "score/full.pdf") ||
    files.find((file) => file.endsWith(".pdf"));
  const svg = files.find((file) => file.endsWith(".svg"));
  const hasResult = detail.stems.length > 0 && Boolean(fullMidi);
  const isRunning = job.status === "running" || job.status === "starting";

  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!isRunning) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [isRunning]);

  useEffect(() => {
    setTab("mix");
    setFocusTrack(null);
  }, [projectId]);

  const run = async () => {
    setBusy(true);
    try {
      await onRun(preset, force);
    } finally {
      setBusy(false);
    }
  };

  const stageState = (index: number): "done" | "active" | "error" | "pending" => {
    if (job.status === "done") return "done";
    if (job.status === "error" && job.stage === STAGES[index]) return "error";
    if (job.index && index < job.index) return "done";
    if (job.stage === STAGES[index]) return "active";
    return "pending";
  };

  const startedAt = job.started_at ? Date.parse(job.started_at) : Number.NaN;
  const elapsedSeconds =
    isRunning && Number.isFinite(startedAt)
      ? Math.max(0, Math.floor((now - startedAt) / 1000))
      : 0;
  const elapsedLabel =
    elapsedSeconds >= 3600
      ? `${Math.floor(elapsedSeconds / 3600)}:${String(
          Math.floor((elapsedSeconds % 3600) / 60),
        ).padStart(2, "0")}:${String(elapsedSeconds % 60).padStart(2, "0")}`
      : `${Math.floor(elapsedSeconds / 60)}:${String(elapsedSeconds % 60).padStart(2, "0")}`;
  const stepMessage = isRunning
    ? (job.message || "").replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, "")
    : "";

  return (
    <div className="project-view">
      <header className="project-header">
        <div className="project-identity">
          <div className="project-cover" aria-hidden="true">
            <span>♪</span>
            <i />
            <i />
            <i />
          </div>
          <div>
            <div className="project-kicker">
              {detail.project.preset === "quality" ? "质量档" : "快速档"} · PROJECT
            </div>
            <h2>{detail.project.title || projectId}</h2>
            <div className="project-sub">
              {detail.project.original_filename} · {detail.project.created_at}
            </div>
          </div>
        </div>
        <span className={`status-pill ${job.status}`}>{STATUS_LABELS[job.status] ?? job.status}</span>
      </header>

      <div className="analysis-row">
        {detail.analysis.bpm && <span className="badge">{detail.analysis.bpm} BPM</span>}
        {detail.analysis.time_signature && <span className="badge">{detail.analysis.time_signature}</span>}
        {detail.analysis.key && <span className="badge">{detail.analysis.key}</span>}
        {detail.analysis.beat_source && <span className="badge ghost">{detail.analysis.beat_source}</span>}
        <span className="badge ghost">{detail.tracks.length} 轨</span>
      </div>

      <section className="progress-card">
        <div className="progress-top">
          <span>
            {isRunning
              ? `正在处理：${STAGE_LABELS[job.stage ?? ""] ?? job.stage ?? "准备中"} · 已用 ${elapsedLabel}`
              : job.message || STATUS_LABELS[job.status] || ""}
          </span>
          <span>{job.progress ?? 0}%</span>
        </div>
        <div className={`progress-track ${isRunning ? "running" : ""}`}>
          <div className="progress-fill" style={{ width: `${job.progress ?? 0}%` }} />
        </div>
        {isRunning && stepMessage && <div className="progress-step">{stepMessage}</div>}
        <div className="stage-row">
          {STAGES.map((stage, index) => (
            <div key={stage} className={`stage ${stageState(index)}`}>
              <span className="stage-dot" />
              {STAGE_LABELS[stage]}
            </div>
          ))}
        </div>
        {job.status === "error" && <div className="error">{job.message}</div>}
      </section>

      <section className="run-bar">
        <select value={preset} onChange={(event) => setPreset(event.target.value)}>
          <option value="fast">快速</option>
          <option value="quality">质量（最慢 · 最高精度）</option>
        </select>
        <label className="checkbox">
          <input type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} />
          忽略缓存
        </label>
        <button className="primary" onClick={run} disabled={isRunning || busy}>
          {isRunning ? "处理中…" : "重新运行"}
        </button>
        <div className="spacer" />
        <div className="resource-links">
          {fullMidi && (
            <a className="resource-link" href={fileUrl(projectId, fullMidi)} download>
              MIDI
            </a>
          )}
          {musicxml && (
            <a className="resource-link" href={fileUrl(projectId, musicxml)} download>
              MusicXML
            </a>
          )}
          {pdf && (
            <a className="resource-link" href={fileUrl(projectId, pdf)} target="_blank" rel="noreferrer">
              PDF
            </a>
          )}
        </div>
      </section>

      <nav className="tabs">
        {(
          [
            ["mix", "分轨"],
            ["tracks", "轨道"],
            ["midi", "钢琴卷帘"],
            ["score", "乐谱"],
            ["log", "日志"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            className={tab === key ? "tab active" : "tab"}
            onClick={() => {
              setTab(key);
              if (key === "midi") setFocusTrack(null);
            }}
          >
            {label}
          </button>
        ))}
      </nav>

      <section className="tab-body">
        {tab === "mix" &&
          (hasResult ? (
            <StemMixer projectId={projectId} stems={detail.stems} />
          ) : (
            <div className="placeholder">等待分离完成…</div>
          ))}

        {tab === "tracks" && (
          <TrackManager
            projectId={projectId}
            tracks={detail.tracks}
            files={files}
            onRefresh={onRefresh}
            onEditTrack={(index) => {
              setFocusTrack(index);
              setTab("midi");
            }}
            onOpenMix={() => setTab("mix")}
          />
        )}

        {tab === "midi" &&
          (fullMidi ? (
            <PianoRoll
              projectId={projectId}
              url={fileUrl(projectId, fullMidi)}
              confidenceUrl={
                files.includes("midi/final/confidence.json")
                  ? fileUrl(projectId, "midi/final/confidence.json")
                  : undefined
              }
              initialTrackIndex={focusTrack ?? undefined}
            />
          ) : (
            <div className="placeholder">还没有 MIDI 结果</div>
          ))}

        {tab === "score" && (
          <ScoreView
            projectId={projectId}
            files={files}
            version={job.updated_at || String(job.progress ?? "")}
            sourceUrl={detail.source_audio}
          />
        )}

        {tab === "log" && <LogView projectId={projectId} />}
      </section>
    </div>
  );
}
