import type {
  DoctorInfo,
  InstrumentProfile,
  ProjectDetail,
  ProjectSummary,
  TrackInfo,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.text();
    let message = body || response.statusText;
    try {
      const payload = JSON.parse(body) as { detail?: unknown };
      if (typeof payload?.detail === "string") {
        message = payload.detail;
      }
    } catch {
      // Not JSON: keep the raw response body.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export async function listProjects(): Promise<ProjectSummary[]> {
  const data = await request<{ projects: ProjectSummary[] }>("/api/projects");
  return data.projects;
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/api/projects/${projectId}`);
}

export async function deleteProject(projectId: string): Promise<void> {
  await request(`/api/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
}

export async function listInstruments(): Promise<InstrumentProfile[]> {
  const data = await request<{ instruments: InstrumentProfile[] }>("/api/instruments");
  return data.instruments;
}

export async function uploadProject(
  file: File,
  preset: string,
  title: string,
  mode: string = "full",
  instrumentId: string = "",
): Promise<ProjectDetail> {
  const form = new FormData();
  form.append("file", file);
  form.append("preset", preset);
  form.append("title", title);
  form.append("mode", mode);
  if (instrumentId) {
    form.append("instrument_id", instrumentId);
  }
  form.append("start", "true");
  return request<ProjectDetail>("/api/projects", { method: "POST", body: form });
}

export interface TrackPatchPayload {
  instrument_id?: string;
  display_name?: string;
  delete?: boolean;
}

export async function updateTrack(
  projectId: string,
  index: number,
  patch: TrackPatchPayload,
): Promise<TrackInfo[]> {
  const data = await request<{ tracks: TrackInfo[] }>(
    `/api/projects/${projectId}/tracks/${index}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    },
  );
  return data.tracks;
}

export async function uploadStem(
  projectId: string,
  instrumentId: string,
  file: File,
): Promise<{ status: string; instrument_id: string; manual_stems: string[] }> {
  const form = new FormData();
  form.append("file", file);
  form.append("instrument_id", instrumentId);
  return request(`/api/projects/${projectId}/stems`, { method: "POST", body: form });
}

export async function runProject(projectId: string, preset: string, force: boolean): Promise<void> {
  await request(`/api/projects/${projectId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ preset, force }),
  });
}

export async function getDoctor(): Promise<DoctorInfo> {
  return request<DoctorInfo>("/api/doctor");
}

export async function getLog(projectId: string): Promise<string[]> {
  const data = await request<{ lines: string[] }>(`/api/projects/${projectId}/log`);
  return data.lines;
}

export function fileUrl(projectId: string, relative: string): string {
  const encoded = relative
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  return `/api/projects/${projectId}/files/${encoded}`;
}

export function openJobSocket(projectId: string, onMessage: (payload: any) => void): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/api/projects/${projectId}/events`);
  socket.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data));
    } catch {
      // ignore malformed frames
    }
  };
  return socket;
}
