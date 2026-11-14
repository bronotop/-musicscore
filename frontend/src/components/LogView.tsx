import { useEffect, useRef, useState } from "react";
import { getLog } from "../api";

interface Props {
  projectId: string;
}

export function LogView({ projectId }: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const ref = useRef<HTMLPreElement>(null);

  useEffect(() => {
    let stopped = false;
    const load = async () => {
      try {
        const next = await getLog(projectId);
        if (!stopped) setLines(next);
      } catch {
        // ignore transient errors while the worker starts
      }
    };
    load();
    const timer = window.setInterval(load, 2000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [projectId]);

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines]);

  return (
    <pre className="log" ref={ref}>
      {lines.join("\n") || "暂无日志"}
    </pre>
  );
}
