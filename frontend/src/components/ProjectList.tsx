import { useEffect, useState } from "react";
import type { ProjectSummary } from "../types";

interface Props {
  projects: ProjectSummary[];
  selected: string | null;
  onSelect: (projectId: string) => void;
  onDelete: (projectId: string, title: string) => void;
}

interface MenuState {
  x: number;
  y: number;
  project: ProjectSummary;
}

export function ProjectList({ projects, selected, onSelect, onDelete }: Props) {
  const [menu, setMenu] = useState<MenuState | null>(null);

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenu(null);
    };
    window.addEventListener("click", close);
    window.addEventListener("contextmenu", close);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("contextmenu", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [menu]);

  const openMenu = (event: React.MouseEvent, project: ProjectSummary) => {
    event.preventDefault();
    event.stopPropagation();
    setMenu({
      x: Math.min(event.clientX, window.innerWidth - 170),
      y: Math.min(event.clientY, window.innerHeight - 64),
      project,
    });
  };

  return (
    <section className="projects">
      <div className="section-title">项目</div>
      {projects.length === 0 && <div className="muted">还没有项目</div>}
      <div className="project-list">
        {projects.map((project) => (
          <button
            key={project.project_id}
            className={`project-item ${selected === project.project_id ? "active" : ""}`}
            onClick={() => onSelect(project.project_id)}
            onContextMenu={(event) => openMenu(event, project)}
          >
            <span className={`status-dot ${project.status}`} />
            <span className="project-info">
              <span className="project-title">{project.title}</span>
              <span className="project-meta">
                {project.status === "running" ? `${project.progress ?? 0}%` : project.status}
                {project.created_at ? ` · ${project.created_at.replace("T", " ").slice(5, 16)}` : ""}
              </span>
            </span>
          </button>
        ))}
      </div>

      {menu && (
        <div
          className="context-menu"
          style={{ left: menu.x, top: menu.y }}
          role="menu"
          onClick={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            className="danger"
            role="menuitem"
            onClick={() => {
              const target = menu.project;
              setMenu(null);
              onDelete(target.project_id, target.title);
            }}
          >
            删除项目
          </button>
        </div>
      )}
    </section>
  );
}
