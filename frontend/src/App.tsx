import { useCallback, useEffect, useState } from "react";
import {
  deleteProject,
  getDoctor,
  getProject,
  listProjects,
  openJobSocket,
  runProject,
  uploadProject,
} from "./api";
import type { DoctorInfo, ProjectDetail, ProjectSummary } from "./types";
import { UploadPanel } from "./components/UploadPanel";
import { ProjectList } from "./components/ProjectList";
import { ProjectView } from "./components/ProjectView";

export default function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [doctor, setDoctor] = useState<DoctorInfo | null>(null);
  const [error, setError] = useState("");

  const refreshProjects = useCallback(async () => {
    try {
      setProjects(await listProjects());
    } catch (exc) {
      setError(String(exc));
    }
  }, []);

  const refreshDetail = useCallback(async (id: string) => {
    try {
      setDetail(await getProject(id));
    } catch (exc) {
      setError(String(exc));
    }
  }, []);

  useEffect(() => {
    refreshProjects();
    getDoctor().then(setDoctor).catch(() => undefined);
  }, [refreshProjects]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    refreshDetail(selected);
    const socket = openJobSocket(selected, (payload) => {
      setDetail((current) => (current ? { ...current, job: payload } : current));
      if (payload.status === "done" || payload.status === "error") {
        refreshDetail(selected);
        refreshProjects();
      }
    });
    return () => socket.close();
  }, [selected, refreshDetail, refreshProjects]);

  const handleUpload = async (
    file: File,
    preset: string,
    title: string,
    mode = "full",
    instrumentId = "",
  ) => {
    setError("");
    const created = await uploadProject(file, preset, title, mode, instrumentId);
    await refreshProjects();
    setSelected(created.project.project_id);
    setDetail(created);
  };

  const handleRun = async (preset: string, force: boolean) => {
    if (!selected) return;
    try {
      await runProject(selected, preset, force);
      await refreshDetail(selected);
    } catch (exc) {
      setError(String(exc));
    }
  };

  const handleDeleteProject = async (projectId: string, title: string) => {
    const project = projects.find((item) => item.project_id === projectId);
    const message = [
      `删除项目「${title}」？`,
      project?.status === "running" ? "正在运行的任务会被中止。" : "",
      "分轨、MIDI 和乐谱都会被删除，无法恢复。",
    ]
      .filter(Boolean)
      .join("\n");
    if (!window.confirm(message)) return;

    setError("");
    try {
      await deleteProject(projectId);
      if (selected === projectId) {
        setSelected(null);
        setDetail(null);
      }
      await refreshProjects();
    } catch (exc) {
      setError(String(exc));
    }
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">♪</span>
          <div>
            <h1>music2score</h1>
            <p>分离 · 扒谱 · 乐谱</p>
          </div>
        </div>

        <UploadPanel onUpload={handleUpload} />

        <ProjectList
          projects={projects}
          selected={selected}
          onSelect={setSelected}
          onDelete={handleDeleteProject}
        />

        {doctor && (
          <div className={`doctor ${doctor.cuda ? "ok" : "warn"}`}>
            <div className="doctor-head">
              <span className="doctor-title">{doctor.cuda ? "GPU 就绪" : "CPU 模式"}</span>
              <span className="doctor-space">{doctor.free_space_gb} GB 可用</span>
            </div>
            <div className="doctor-grid">
              <div className="doctor-item">
                <span className={`doctor-dot ${doctor.cuda ? "on" : "off"}`} />
                {doctor.gpu ?? "未检测到 CUDA"}
              </div>
              <div className="doctor-item">
                <span className={`doctor-dot ${doctor.torch ? "on" : "off"}`} />
                torch {doctor.torch ?? "未安装"}
              </div>
              <div className="doctor-item">
                <span className={`doctor-dot ${doctor.ffmpeg ? "on" : "off"}`} />
                ffmpeg
              </div>
              <div className="doctor-item">
                <span className={`doctor-dot ${doctor.musescore ? "on" : "off"}`} />
                MuseScore
              </div>
              <div className="doctor-item">
                <span className={`doctor-dot ${doctor.muscriptor_weights ? "on" : "off"}`} />
                MuScriptor
              </div>
              <div className="doctor-item">
                <span className={`doctor-dot ${doctor.lyrics_model ? "on" : "off"}`} />
                歌词模型
              </div>
              <div className="doctor-item">
                <span className={`doctor-dot ${doctor.game_model ? "on" : "off"}`} />
                GAME 人声
              </div>
              <div className="doctor-item">
                <span className="doctor-dot on" />
                Python {doctor.python}
              </div>
            </div>
          </div>
        )}

        {error && <div className="error">{error}</div>}
      </aside>

      <main className="main">
        {selected && detail ? (
          <ProjectView
            detail={detail}
            onRun={handleRun}
            onRefresh={() => (selected ? refreshDetail(selected) : undefined)}
          />
        ) : (
          <div className="empty">
            <div className="empty-visual" aria-hidden="true">
              <div className="empty-orb">♫</div>
              <div className="empty-bars">
                <span />
                <span />
                <span />
                <span />
                <span />
              </div>
            </div>
            <h2>导入一首歌，自动生成分轨与乐谱</h2>
            <p>支持 mp3 / wav / flac / m4a。首次运行会加载模型，之后会命中缓存。</p>
            <div className="empty-hint">拖入音频 · 自动分离 · 生成 MIDI 与乐谱</div>
          </div>
        )}
      </main>
    </div>
  );
}
