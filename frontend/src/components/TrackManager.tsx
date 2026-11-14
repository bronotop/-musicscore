import { useEffect, useMemo, useRef, useState } from "react";
import { fileUrl, listInstruments, updateTrack, uploadStem } from "../api";
import { useTrackAudition } from "../hooks/useTrackAudition";
import type { InstrumentProfile, TrackInfo } from "../types";

const FAMILY_LABELS: Record<string, string> = {
  bass: "低音",
  brass: "铜管",
  chinese: "民乐",
  effect: "音效",
  electronic: "电子",
  ethnic: "民族",
  keyboard: "键盘",
  other: "其他",
  percussion: "打击乐",
  plucked: "弹拨",
  reed: "簧管",
  strings: "弦乐",
  synth: "合成器",
  voice: "人声",
  woodwind: "木管",
};

const SOURCE_LABELS: Record<string, string> = {
  core: "主轨",
  solo: "独奏",
  extra: "附加",
  manual: "手动",
};

const CLEF_LABELS: Record<string, string> = {
  treble: "高音谱号",
  bass: "低音谱号",
  alto: "中音谱号",
  grand: "大谱表",
  percussion: "打击乐谱",
  treble8vb: "低八度高音谱号",
};

function instrumentLabel(profile: InstrumentProfile): string {
  if (profile.display_name && profile.display_name !== profile.name_en) {
    return `${profile.display_name} (${profile.name_en})`;
  }
  return profile.name_en || profile.id;
}

function draftsFor(tracks: TrackInfo[]): Record<number, string> {
  const drafts: Record<number, string> = {};
  tracks.forEach((track, index) => {
    drafts[index] = track.display_name || track.stem;
  });
  return drafts;
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0");
  return `${minutes}:${rest}`;
}

function normalizePartName(value: string): string {
  return value
    .toLowerCase()
    .replace(/\.[^.]+$/, "")
    .replace(/^\d+_/, "")
    .replace(/[^\p{L}\p{N}]+/gu, "");
}

function findPart(files: string[] | undefined, track: TrackInfo): string | null {
  if (!files?.length) return null;
  const target = normalizePartName(track.display_name || track.stem);
  if (!target) return null;
  const matches = files.filter((file) => {
    if (!file.startsWith("score/parts/") || !file.endsWith(".musicxml")) {
      return false;
    }
    const name = file.split("/").pop() ?? "";
    return normalizePartName(name) === target;
  });
  return matches.length === 1 ? matches[0] : null;
}

interface Props {
  projectId: string;
  tracks: TrackInfo[];
  files?: string[];
  onRefresh?: () => Promise<void> | void;
  onEditTrack?: (index: number) => void;
  onOpenMix?: () => void;
}

export function TrackManager({
  projectId,
  tracks: incomingTracks,
  files,
  onRefresh,
  onEditTrack,
  onOpenMix,
}: Props) {
  const [instruments, setInstruments] = useState<InstrumentProfile[]>([]);
  const [tracks, setTracks] = useState<TrackInfo[]>(incomingTracks);
  const [drafts, setDrafts] = useState<Record<number, string>>(() =>
    draftsFor(incomingTracks),
  );
  const [busyIndex, setBusyIndex] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [uploadInstrument, setUploadInstrument] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const audition = useTrackAudition(projectId);

  useEffect(() => {
    setTracks(incomingTracks);
    setDrafts(draftsFor(incomingTracks));
  }, [incomingTracks]);

  useEffect(() => {
    setUploadFile(null);
    if (fileRef.current) fileRef.current.value = "";
    setStatus("");
    setError("");
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    listInstruments()
      .then((profiles) => {
        if (cancelled) return;
        setInstruments(profiles);
        setUploadInstrument((current) => {
          if (current && profiles.some((profile) => profile.id === current)) {
            return current;
          }
          return profiles.find((profile) => profile.id === "other")?.id ?? profiles[0]?.id ?? "";
        });
      })
      .catch((exc) => {
        if (!cancelled) setError(String(exc));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const groups = useMemo(() => {
    const grouped = new Map<string, InstrumentProfile[]>();
    for (const profile of instruments) {
      const list = grouped.get(profile.family) ?? [];
      list.push(profile);
      grouped.set(profile.family, list);
    }
    return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [instruments]);

  const audioCount = tracks.filter((track) => Boolean(track.audio)).length;
  const midiOnlyCount = tracks.length - audioCount;

  const applyTracks = (updated: TrackInfo[]) => {
    setTracks(updated);
    setDrafts(draftsFor(updated));
  };

  const commitName = async (index: number) => {
    const track = tracks[index];
    if (!track || busyIndex !== null) return;
    const current = track.display_name || track.stem;
    const next = (drafts[index] ?? "").trim();
    if (!next) {
      setDrafts((prev) => ({ ...prev, [index]: current }));
      return;
    }
    if (next === current) return;
    setBusyIndex(index);
    setError("");
    setStatus("");
    try {
      applyTracks(await updateTrack(projectId, index, { display_name: next }));
      setStatus("音轨名称已更新，正在重新生成乐谱…");
      await onRefresh?.();
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusyIndex(null);
    }
  };

  const changeInstrument = async (index: number, instrumentId: string) => {
    if (!instrumentId) return;
    setBusyIndex(index);
    setError("");
    setStatus("");
    try {
      applyTracks(await updateTrack(projectId, index, { instrument_id: instrumentId }));
      setStatus("乐器已更新，正在重新生成乐谱…");
      await onRefresh?.();
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusyIndex(null);
    }
  };

  const removeTrack = async (index: number) => {
    const track = tracks[index];
    if (!track || busyIndex !== null) return;
    const name = track.display_name || track.stem;
    if (
      !window.confirm(
        `从 MIDI / 总谱移除「${name}」？\n\n分轨音频会保留，可在「分轨」页继续试听和混音。`,
      )
    ) {
      return;
    }
    audition.stop();
    setBusyIndex(index);
    setError("");
    setStatus("");
    try {
      applyTracks(await updateTrack(projectId, index, { delete: true }));
      setStatus("音轨已从 MIDI / 乐谱移除，分轨音频保留。");
      await onRefresh?.();
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusyIndex(null);
    }
  };

  const submitStem = async () => {
    if (!uploadFile) {
      setError("请选择 WAV 分轨文件");
      return;
    }
    if (!uploadInstrument) {
      setError("请选择分轨对应的乐器");
      return;
    }
    setUploading(true);
    setError("");
    setStatus("");
    try {
      const result = await uploadStem(projectId, uploadInstrument, uploadFile);
      setUploadFile(null);
      if (fileRef.current) fileRef.current.value = "";
      setStatus(
        `已上传 ${result.instrument_id} 分轨，正在重新转录、合并并生成乐谱…`,
      );
      await onRefresh?.();
    } catch (exc) {
      setError(String(exc));
    } finally {
      setUploading(false);
    }
  };

  return (
    <section className="track-manager">
      <div className="track-manager-head">
        <div>
          <span className="section-title">轨道控制台</span>
          <div className="track-hint">
            管理 MIDI 轨与配器；音频混音在「分轨」页。
          </div>
        </div>
        {onOpenMix && (
          <button className="chip" type="button" onClick={onOpenMix}>
            去分轨页
          </button>
        )}
      </div>

      <div className="track-summary">
        <span className="track-badge">{tracks.length} 轨</span>
        <span className="track-badge ghost">{audioCount} 有音频</span>
        <span className="track-badge ghost">{midiOnlyCount} 仅 MIDI</span>
        <span className="track-summary-hint">
          试听：核心轨播分轨音频，附加轨为 MIDI 合成
        </span>
      </div>

      {tracks.length === 0 && (
        <div className="placeholder">
          还没有音轨。完成转录后可在这里调整，也可以直接在下方补充分轨。
        </div>
      )}

      {tracks.length > 0 && (
        <div className="track-list">
          {tracks.map((track, index) => {
            const busy = busyIndex === index;
            const instrumentId = track.instrument_id ?? "";
            const known = instruments.some((profile) => profile.id === instrumentId);
            const source = track.source ?? "other";
            const isPlaying = audition.active?.index === index;
            const progress =
              isPlaying && audition.duration > 0
                ? Math.min(100, (audition.progress / audition.duration) * 100)
                : 0;
            const part = findPart(files, track);
            const canPreview = Boolean(
              track.audio || (track.midi && !track.midi.endsWith("full.mid")),
            );
            const confidence =
              typeof track.confidence === "number" ? track.confidence : null;
            return (
              <div
                className={`track-row${isPlaying ? " playing" : ""}`}
                data-source={source}
                key={`${index}-${track.stem}`}
              >
                <span className="track-index">
                  <span className={`track-source-dot ${source}`} aria-hidden="true" />
                  {index + 1}
                </span>
                <div className="track-main">
                  <div className="track-title-row">
                    <input
                      className="track-name-input"
                      value={drafts[index] ?? ""}
                      disabled={busy}
                      onChange={(event) =>
                        setDrafts((prev) => ({ ...prev, [index]: event.target.value }))
                      }
                      onBlur={() => commitName(index)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.currentTarget.blur();
                        } else if (event.key === "Escape") {
                          setDrafts((prev) => ({
                            ...prev,
                            [index]: track.display_name || track.stem,
                          }));
                          event.currentTarget.blur();
                        }
                      }}
                    />
                    <span className="track-badge">
                      {SOURCE_LABELS[source] ?? source}
                    </span>
                    <span className="track-badge ghost">{track.notes} 音符</span>
                    {confidence !== null && (
                      <span className="track-badge ghost">
                        置信 {Math.round(confidence * 100)}%
                      </span>
                    )}
                    {track.is_drum && <span className="track-badge ghost">打击乐</span>}
                  </div>
                  <div className="track-sub">
                    {track.stem} · GM {track.program}
                    {track.clef ? ` · ${CLEF_LABELS[track.clef] ?? track.clef}` : ""}
                    {track.transpose
                      ? ` · 移调 ${track.transpose > 0 ? "+" : ""}${track.transpose}`
                      : ""}
                    {track.model ? ` · ${track.model}` : ""}
                    {!track.audio && !track.is_drum ? " · 无独立音频，试听为合成音" : ""}
                  </div>
                  <div className="track-actions">
                    <span
                      className={`track-audio-kind ${track.audio ? "has-audio" : "midi-only"}`}
                    >
                      {track.audio ? "有分轨音频" : "仅 MIDI"}
                    </span>
                    <button
                      className={`chip${isPlaying ? " active" : ""}`}
                      type="button"
                      onClick={() => void audition.play(index, track)}
                      disabled={!canPreview}
                      aria-pressed={isPlaying}
                    >
                      {isPlaying ? "■ 停止" : track.audio ? "▶ 试听" : "▶ MIDI 试听"}
                    </button>
                    {onEditTrack && (
                      <button
                        className="chip"
                        type="button"
                        onClick={() => onEditTrack(index)}
                      >
                        编辑音符
                      </button>
                    )}
                    {track.midi && (
                      <a
                        className="chip"
                        href={fileUrl(projectId, track.midi)}
                        download
                      >
                        MIDI
                      </a>
                    )}
                    {part && (
                      <a
                        className="chip"
                        href={fileUrl(projectId, part)}
                        download
                      >
                        分谱
                      </a>
                    )}
                    {isPlaying && (
                      <span className="track-audio-time">
                        {formatTime(audition.progress)} / {formatTime(audition.duration)}
                      </span>
                    )}
                  </div>
                  {isPlaying && (
                    <div
                      className="track-progress"
                      role="progressbar"
                      aria-label="试听进度"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.round(progress)}
                    >
                      <span style={{ width: `${progress}%` }} />
                    </div>
                  )}
                </div>
                <select
                  className="track-instrument"
                  value={instrumentId}
                  disabled={busyIndex !== null || !instruments.length}
                  onChange={(event) => changeInstrument(index, event.target.value)}
                  title="更换乐器"
                >
                  {!instrumentId && <option value="">未指定</option>}
                  {instrumentId && !known && (
                    <option value={instrumentId}>
                      {instruments.length ? instrumentId : "加载乐器…"}
                    </option>
                  )}
                  {groups.map(([family, profiles]) => (
                    <optgroup key={family} label={FAMILY_LABELS[family] ?? family}>
                      {profiles.map((profile) => (
                        <option key={profile.id} value={profile.id}>
                          {instrumentLabel(profile)}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
                <button
                  className="track-delete"
                  onClick={() => removeTrack(index)}
                  disabled={busyIndex !== null || tracks.length <= 1}
                  title={
                    tracks.length <= 1
                      ? "至少保留一条音轨"
                      : "从 MIDI/乐谱移除，保留分轨音频"
                  }
                >
                  移除
                </button>
              </div>
            );
          })}
        </div>
      )}

      {error && <div className="error">{error}</div>}
      {audition.error && <div className="error">{audition.error}</div>}
      {status && <div className="track-status">{status}</div>}

      <div className="stem-upload">
        <div className="track-manager-head">
          <span className="section-title">补充分轨</span>
        </div>
        <div className="stem-upload-row">
          <input
            ref={fileRef}
            type="file"
            accept=".wav,audio/wav,audio/x-wav"
            onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
          />
          <select
            className="track-instrument"
            value={uploadInstrument}
            onChange={(event) => setUploadInstrument(event.target.value)}
            disabled={!instruments.length}
            title="分轨乐器"
          >
            {!instruments.length && <option value="">加载乐器…</option>}
            {groups.map(([family, profiles]) => (
              <optgroup key={family} label={FAMILY_LABELS[family] ?? family}>
                {profiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {instrumentLabel(profile)}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          <button
            className="primary compact"
            onClick={submitStem}
            disabled={uploading || busyIndex !== null}
          >
            {uploading ? "上传中…" : "上传分轨"}
          </button>
        </div>
        <div className="stem-upload-hint">
          WAV 保存为 <code>stems/&lt;乐器&gt;.wav</code>；核心乐器会替换对应分轨，其他乐器会增加一条附加轨。
          上传后会重新运行转录、合并与乐谱生成。
        </div>
      </div>
    </section>
  );
}
