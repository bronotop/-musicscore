import { useEffect, useRef, useState } from "react";
import { fileUrl } from "../api";

interface Props {
  projectId: string;
  files: string[];
  version?: string;
  sourceUrl?: string;
}

interface TimemapEvent {
  tstamp: number;
  qstamp?: number;
  tempo?: number;
  on?: string[];
  off?: string[];
}

interface SvgPage {
  name: string;
  html: string;
}

function pageNumber(name: string): number {
  const match = name.match(/-p(\d+)\.svg$/i);
  return match ? Number(match[1]) : 0;
}

export function ScoreView({ projectId, files, version, sourceUrl }: Props) {
  const svgFiles = files
    .filter((file) => file.endsWith(".svg"))
    .sort((a, b) => pageNumber(a) - pageNumber(b));
  const xml = files.find((file) => file.endsWith("score/full.musicxml"));
  const pdf =
    files.find((file) => file === "score/full.pdf") ||
    files.find((file) => file.endsWith(".pdf"));
  const parts = files.filter(
    (file) => file.includes("score/parts/") && file.endsWith(".musicxml")
  );
  const timemapFile = files.find((file) => file.endsWith("score/full.timemap.json"));

  const [pages, setPages] = useState<SvgPage[]>([]);
  const [events, setEvents] = useState<TimemapEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [follow, setFollow] = useState(true);
  const [zoom, setZoom] = useState<number>(() => {
    if (typeof window === "undefined") return 0.85;
    const stored = Number(window.localStorage.getItem("m2s.score.zoom"));
    return [1, 0.85, 0.75, 0.65].includes(stored) ? stored : 0.85;
  });
  const [audioError, setAudioError] = useState("");
  const [error, setError] = useState("");

  const pagesRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const eventsRef = useRef<TimemapEvent[]>([]);
  const eventIndexRef = useRef(0);
  const activeRef = useRef<Set<string>>(new Set());
  const lastTimeRef = useRef(0);
  const lastScrollAtRef = useRef(0);
  const anchorStaffRef = useRef<Element | null>(null);
  const anchorReleaseRef = useRef(0);
  const idTimesRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    eventsRef.current = events;
    const idTimes = new Map<string, number>();
    for (const event of events) {
      for (const id of event.on ?? []) {
        if (!idTimes.has(id)) idTimes.set(id, event.tstamp);
      }
    }
    idTimesRef.current = idTimes;
  }, [events]);

  const fileKey = files.join("|");

  useEffect(() => {
    let cancelled = false;
    setError("");
    setPages([]);
    setLoading(true);
    const suffix = version ? `?v=${encodeURIComponent(version)}` : "";
    const collected: (SvgPage | null)[] = new Array(svgFiles.length).fill(null);
    let completed = 0;

    svgFiles.forEach((name, index) => {
      const load = async () => {
        try {
          const response = await fetch(`${fileUrl(projectId, name)}${suffix}`, {
            cache: "no-store",
          });
          if (!response.ok) return;
          const html = await response.text();
          if (!cancelled) collected[index] = { name, html };
        } catch (exc) {
          if (!cancelled) setError(String(exc));
        } finally {
          if (cancelled) return;
          completed += 1;
          setPages(collected.filter((page): page is SvgPage => Boolean(page)));
          if (completed >= svgFiles.length) setLoading(false);
        }
      };
      void load();
    });
    if (svgFiles.length === 0) setLoading(false);

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, fileKey, version]);

  useEffect(() => {
    let cancelled = false;
    setEvents([]);
    if (!timemapFile) return () => {
      cancelled = true;
    };
    const suffix = version ? `?v=${encodeURIComponent(version)}` : "";
    fetch(`${fileUrl(projectId, timemapFile)}${suffix}`, { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : []))
      .then((data) => {
        if (cancelled) return;
        const ordered = Array.isArray(data)
          ? [...data].sort((a: TimemapEvent, b: TimemapEvent) => a.tstamp - b.tstamp)
          : [];
        setEvents(ordered);
      })
      .catch(() => {
        if (!cancelled) setEvents([]);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, timemapFile, version]);

  const clearActive = () => {
    for (const id of activeRef.current) {
      document.getElementById(id)?.classList.remove("score-active");
    }
    activeRef.current.clear();
    eventIndexRef.current = 0;
    lastTimeRef.current = 0;
    lastScrollAtRef.current = 0;
    anchorStaffRef.current = null;
    anchorReleaseRef.current = 0;
  };

  const applyEvents = (seconds: number) => {
    const list = eventsRef.current;
    if (!list.length) return;
    const ms = seconds * 1000;
    if (ms < lastTimeRef.current - 60) clearActive();
    while (
      eventIndexRef.current < list.length &&
      list[eventIndexRef.current].tstamp <= ms + 35
    ) {
      const event = list[eventIndexRef.current];
      event.off?.forEach((id) => {
        if (activeRef.current.delete(id)) {
          document.getElementById(id)?.classList.remove("score-active");
        }
      });
      event.on?.forEach((id) => {
        activeRef.current.add(id);
        document.getElementById(id)?.classList.add("score-active");
      });
      eventIndexRef.current += 1;
    }
    lastTimeRef.current = ms;

    // Peek slightly ahead so the page starts moving before the next staff
    // sounds; smooth scrolling itself takes a few hundred milliseconds.
    const lookaheadMs = 320;
    const focusIds = new Set(activeRef.current);
    let probe = eventIndexRef.current;
    while (probe < list.length && list[probe].tstamp <= ms + lookaheadMs) {
      const event = list[probe];
      event.off?.forEach((id) => focusIds.delete(id));
      event.on?.forEach((id) => focusIds.add(id));
      probe += 1;
    }

    if (follow && focusIds.size > 0) {
      const container = pagesRef.current;
      if (!container) return;

      // Anchor on the staff, not on an individual note. Every note of one
      // instrument shares a staff, so the page only moves when focus moves
      // to another staff or to the next page -- not on every note onset.
      const staffIds = new Set<string>();
      let topmost: Element | null = null;
      for (const id of focusIds) {
        const note = document.getElementById(id);
        const staff = note?.closest("g.staff");
        if (!staff) continue;
        if (staff.id) staffIds.add(staff.id);
        if (
          !topmost ||
          (staff.compareDocumentPosition(topmost) & Node.DOCUMENT_POSITION_FOLLOWING)
        ) {
          topmost = staff;
        }
      }

      let anchor = anchorStaffRef.current;
      const moment = performance.now();
      const stillActive = Boolean(anchor?.id && staffIds.has(anchor.id));
      if (stillActive) {
        anchorReleaseRef.current = 0;
      } else if (anchor) {
        // Hold the previous staff briefly through short rests so the view
        // does not bounce between melody and accompaniment.
        if (!anchorReleaseRef.current) anchorReleaseRef.current = moment;
        if (moment - anchorReleaseRef.current > 220) {
          anchor = topmost;
          anchorStaffRef.current = anchor;
          anchorReleaseRef.current = 0;
        }
      } else {
        anchor = topmost;
        anchorStaffRef.current = anchor;
      }
      if (!anchor) return;

      const containerRect = container.getBoundingClientRect();
      const staffRect = anchor.getBoundingClientRect();
      // Only scroll when the followed staff approaches either edge.
      const margin = containerRect.height * 0.08;
      const outside =
        staffRect.top < containerRect.top + margin ||
        staffRect.bottom > containerRect.bottom - margin;
      const now = performance.now();
      if (!outside || now - lastScrollAtRef.current < 300) return;

      lastScrollAtRef.current = now;
      const target =
        container.scrollTop +
        (staffRect.top - containerRect.top) -
        containerRect.height * 0.25;
      const maxScroll = container.scrollHeight - container.clientHeight;
      container.scrollTo({
        top: Math.max(0, Math.min(target, maxScroll)),
        behavior: "smooth",
      });
    }
  };

  useEffect(() => {
    clearActive();
  }, [pages]);

  useEffect(() => {
    window.localStorage.setItem("m2s.score.zoom", String(zoom));
  }, [zoom]);

  // Bring the score area into view once the SVGs are ready; the project
  // header and progress card otherwise push most of the score below the fold.
  useEffect(() => {
    if (loading) return;
    const frame = window.requestAnimationFrame(() => {
      const main = document.querySelector(".main");
      const view = document.querySelector(".score-view");
      if (!main || !view) return;
      const top =
        view.getBoundingClientRect().top -
        main.getBoundingClientRect().top +
        main.scrollTop;
      main.scrollTo({ top: Math.max(0, top - 8), behavior: "smooth" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [loading]);

  useEffect(() => {
    clearActive();
  }, [zoom]);

  // Drive highlight/scroll at frame rate instead of relying on the audio
  // element's ~4 Hz timeupdate event.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const audio = audioRef.current;
      if (audio && !audio.paused) {
        applyEvents(audio.currentTime);
      }
      raf = window.requestAnimationFrame(tick);
    };
    raf = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(raf);
  }, [follow]);

  useEffect(() => () => clearActive(), []);

  const onTimeUpdate = (event: React.SyntheticEvent<HTMLAudioElement>) => {
    setTime(event.currentTarget.currentTime);
  };

  const seek = (value: number) => {
    const audio = audioRef.current;
    if (audio) audio.currentTime = value;
    setTime(value);
    clearActive();
    applyEvents(value);
  };

  const onScoreClick = (event: React.MouseEvent<HTMLDivElement>) => {
    const target = event.target as Element;
    const element = target.closest("[id]");
    const id = element?.id;
    if (!id) return;
    const ms = idTimesRef.current.get(id);
    if (ms === undefined) return;
    const seconds = ms / 1000;
    const audio = audioRef.current;
    if (audio) audio.currentTime = seconds;
    setTime(seconds);
    clearActive();
    applyEvents(seconds);
  };

  const source = sourceUrl || `/api/projects/${projectId}/source`;
  const activeSvg = pages.length > 0;

  return (
    <div className="score-view">
      <div className="score-toolbar">
        {xml && (
          <a className="link" href={fileUrl(projectId, xml)} download>
            MusicXML
          </a>
        )}
        {pdf && (
          <a className="link" href={fileUrl(projectId, pdf)} target="_blank" rel="noreferrer">
            PDF
          </a>
        )}
        {parts.length > 0 && (
          <details className="score-parts">
            <summary className="link ghost score-parts-summary">分谱 · {parts.length}</summary>
            <div className="score-parts-list">
              {parts.map((part) => (
                <a key={part} href={fileUrl(projectId, part)} download>
                  {part.split("/").pop()}
                </a>
              ))}
            </div>
          </details>
        )}
        <label className="zoom">
          缩放
          <select value={zoom} onChange={(event) => setZoom(Number(event.target.value))}>
            <option value={1}>100%</option>
            <option value={0.85}>85%</option>
            <option value={0.75}>75%</option>
            <option value={0.65}>65%</option>
          </select>
        </label>
        {pages.length > 1 && <span className="muted">{pages.length} 页</span>}
      </div>

      <div className="score-follow-bar">
        <audio
          ref={audioRef}
          src={source}
          controls
          preload="metadata"
          onTimeUpdate={onTimeUpdate}
          onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
          onSeeked={() => {
            const audio = audioRef.current;
            if (audio) {
              clearActive();
              applyEvents(audio.currentTime);
            }
          }}
          onError={() => setAudioError("浏览器无法播放原曲，可先导出 WAV 后再试。")}
        />
        <label className="checkbox">
          <input
            type="checkbox"
            checked={follow}
            onChange={(event) => setFollow(event.target.checked)}
          />
          乐谱跟随
        </label>
        <span className="muted">
          {loading
            ? "加载乐谱与时间映射…"
            : events.length
              ? `${time.toFixed(1)}s / ${duration ? duration.toFixed(1) : "?"}s · 播放高亮，点击音符跳转`
              : "未生成时间映射，仍可播放原曲"}
        </span>
        <input
          className="seek"
          type="range"
          min={0}
          max={duration || 1}
          step={0.01}
          value={Math.min(time, duration || 1)}
          onChange={(event) => seek(Number(event.target.value))}
        />
      </div>
      {audioError && <div className="pianoroll-hint">{audioError}</div>}

      {activeSvg ? (
        <div className="score-pages" ref={pagesRef} onClick={onScoreClick}>
          {pages.map((page) => (
            <div
              key={page.name}
              className="score-page"
              style={{ width: `${zoom * 100}%` }}
              dangerouslySetInnerHTML={{ __html: page.html }}
            />
          ))}
        </div>
      ) : (
        <div className="placeholder">
          {loading
            ? "加载乐谱…"
            : "乐谱还未生成。分离和转录完成后会自动生成 MusicXML/SVG。"}
        </div>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  );
}
