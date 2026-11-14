import { useEffect, useMemo, useRef, useState } from "react";
import { listInstruments } from "../api";
import type { InstrumentProfile } from "../types";

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

function instrumentLabel(profile: InstrumentProfile): string {
  if (profile.display_name && profile.display_name !== profile.name_en) {
    return `${profile.display_name} (${profile.name_en})`;
  }
  return profile.name_en || profile.id;
}

interface Props {
  onUpload: (
    file: File,
    preset: string,
    title: string,
    mode: string,
    instrumentId: string,
  ) => Promise<void>;
}

export function UploadPanel({ onUpload }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [preset, setPreset] = useState("fast");
  const [mode, setMode] = useState("full");
  const [instrumentId, setInstrumentId] = useState("");
  const [instruments, setInstruments] = useState<InstrumentProfile[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listInstruments()
      .then((profiles) => {
        if (cancelled) return;
        setInstruments(profiles);
        setInstrumentId((current) => {
          if (current && profiles.some((profile) => profile.id === current)) {
            return current;
          }
          return profiles.find((profile) => profile.id === "other")?.id ?? profiles[0]?.id ?? "";
        });
      })
      .catch(() => undefined);
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

  const choose = (candidate: File | null) => {
    setFile(candidate);
    if (candidate && !title) {
      setTitle(candidate.name.replace(/\.[^.]+$/, ""));
    }
  };

  const submit = async () => {
    if (!file) {
      inputRef.current?.click();
      return;
    }
    if (mode === "solo" && !instrumentId) {
      setError("请选择独奏乐器");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await onUpload(
        file,
        preset,
        title || file.name,
        mode,
        mode === "solo" ? instrumentId : "",
      );
      setFile(null);
      setTitle("");
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="upload">
      <div
        className={`dropzone ${dragging ? "dragging" : ""} ${file ? "has-file" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          choose(event.dataTransfer.files[0] ?? null);
        }}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept="audio/*,.flac,.m4a,.mp3,.wav,.ogg"
          hidden
          onChange={(event) => choose(event.target.files?.[0] ?? null)}
        />
        <div className="dropzone-wave" aria-hidden="true">
          <span />
          <span />
          <span />
          <span />
          <span />
          <span />
          <span />
        </div>
        <div className="dropzone-main">{file ? file.name : "拖入音频或点击选择"}</div>
        <div className="dropzone-sub">{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB · 点击更换` : "mp3 / wav / flac / m4a"}</div>
      </div>

      {file && (
        <input
          className="title-input"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="曲名（可选）"
        />
      )}

      <div className="upload-row">
        <select className="upload-grow" value={mode} onChange={(event) => setMode(event.target.value)}>
          <option value="full">完整混音</option>
          <option value="solo">独奏 / 单一乐器</option>
        </select>
      </div>

      {mode === "solo" && (
        <div className="upload-row">
          <select
            className="upload-grow"
            value={instrumentId}
            onChange={(event) => setInstrumentId(event.target.value)}
            disabled={!instruments.length}
            title="独奏乐器"
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
        </div>
      )}

      <div className="upload-row">
        <select value={preset} onChange={(event) => setPreset(event.target.value)}>
          <option value="fast">快速</option>
          <option value="quality">质量（最慢 · 最高精度）</option>
        </select>
        <button className="primary" onClick={submit} disabled={busy}>
          {busy ? "上传中…" : file ? "开始扒谱" : "选择文件"}
        </button>
      </div>

      {error && <div className="error">{error}</div>}
    </section>
  );
}
