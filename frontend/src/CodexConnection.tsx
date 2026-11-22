import {useEffect, useState} from "react";
import {api} from "./api";

type Worker = {status: string; checked: string | null};
export function AIBadge() {
  return <span className="ai-badge" title="Uses Codex when this runs">AI</span>;
}

export function useCodexStatus(owner: boolean) {
  const [worker, setWorker] = useState<Worker>();
  useEffect(() => {
    if (!owner) {setWorker(undefined); return;}
    const controller = new AbortController();
    const refresh = () => api<Worker>("/api/owner/worker-login", "GET", undefined, controller.signal)
      .then(setWorker).catch(() => {});
    void refresh();
    const timer = window.setInterval(refresh, 10000);
    return () => {controller.abort(); window.clearInterval(timer);};
  }, [owner]);

  return owner && worker?.checked && Date.now() - Date.parse(worker.checked) < 240000 ? worker.status : "unknown";
}

export function CodexConnection({status}: {status: string}) {
  const labels: Record<string, string> = {
    connected: "Worker signed in", sign_in: "Worker needs sign-in", missing: "Codex CLI missing on worker",
    unavailable: "Login check failed", unknown: "Waiting for worker status",
  };
  return <section><h2>Codex connection</h2>
    <p role="status">{labels[status] ?? labels.unknown}</p>
    {status !== "connected" && <>
      <p>From the project folder, run the command for your worker and finish signing in with ChatGPT.</p>
      <p>Windows</p><code>.\.venv\Scripts\python.exe -m backend.codex_login</code>
      <p>Docker</p><code>docker compose run --rm worker codex login --device-auth</code>
    </>}
  </section>;
}

export function CodexHint({connect}: {connect: () => void}) {
  return <p className="muted codex-hint">Connect the Codex worker to use these tools.{" "}
    <button className="text-button" type="button" onClick={connect}>Codex settings</button>
  </p>;
}
