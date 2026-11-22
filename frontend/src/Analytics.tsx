import {useEffect, useState} from "react";
import {ChevronLeft, ChevronRight} from "lucide-react";
import {api} from "./api";
import {CatalogMetrics, DiscoveryPanels, useOverviewStats, type OverviewStats} from "./Overview";
import {PageHeader} from "./PageHeader";

type Measure = "applied" | "interview" | "offer" | "assessment" | "closed" | "active" |
  "shortlisted" | "preparing" | "ready" | "requests" | "completed" | "failed" | "limited" |
  "input_tokens" | "cached_input_tokens" | "output_tokens" | "reported" | "duration_ms";
type Counts = Partial<Record<Measure, number>>;
type Point = Counts & {date: string};
type Usage = {
  checked: string;
  available: number;
  pause_until: string | null;
  windows: {used: number; minutes: number | null; resets: string | null}[];
};
export type AnalyticsReport = {
  applications: {
    start: string; end: string; interval: number; series: Point[];
    current: Counts; previous: Counts; pipeline: Counts;
    families: (Counts & {name: string})[];
    family_series?: Record<string, Point[]>;
    employers: [string, number][]; sources: [string, number][];
    cohort_interviews: number; cohort_offers: number; median_response_days: number | null;
  };
  codex: {totals: Counts; series: Point[]; kinds: (Counts & {name: string})[]};
  usage: Usage | null;
};

const applicationMeasures = [["applied", "Applications"], ["interview", "Interviews"], ["offer", "Offers"],
  ["assessment", "Assessments"], ["closed", "Closed"]] as const;
const kindLabels: Record<string, string> = {screening: "Eligibility and fit", resume: "Résumé", cover: "Cover letter", repair: "PDF repair"};
const number = (value: number) => value.toLocaleString();
const shortDate = (day: string) => new Date(day + "T12:00:00").toLocaleDateString(undefined, {month: "short", day: "numeric"});

export function dateKey(day: Date) {
  return [day.getFullYear(), String(day.getMonth() + 1).padStart(2, "0"), String(day.getDate()).padStart(2, "0")].join("-");
}

export function moveDate(day: string, delta: number) {
  const value = new Date(day + "T12:00:00");
  value.setDate(value.getDate() + delta);
  return dateKey(value);
}

export function CodexUsage({usage}: {usage?: Usage | null}) {
  const paused = usage?.pause_until && Date.parse(usage.pause_until) > Date.now();
  return <div className="usage-windows">
    {paused && <p role="status">Queue paused until {new Date(usage.pause_until!).toLocaleString()}.</p>}
    {!usage?.available && <p className="muted">Account usage is unavailable from the Codex worker.</p>}
    {usage?.windows.map((window, index) => {
      const label = window.minutes === 300 ? "5-hour limit" : window.minutes === 10080 ? "Weekly limit"
        : window.minutes ? `${window.minutes.toLocaleString()}-minute limit` : "Usage limit";
      return <div key={index} className="usage-window">
        <span>{label}</span><strong>{window.used}% used</strong>
        <progress value={window.used} max={100} aria-label={label} />
        {window.resets && <small>Resets {new Date(window.resets).toLocaleString()}</small>}
      </div>;
    })}
  </div>;
}

function Trend({title, points, measure, interval, controls}: {
  title: string; points: Point[]; measure: Measure; interval: number; controls?: React.ReactNode;
}) {
  const max = Math.max(0, ...points.map(point => point[measure] || 0));
  return <section className="analytics-panel">
    <div className="panel-heading"><h2>{title}</h2>{controls}</div>
    {max === 0 ? <p className="muted">No activity in this period.</p> : <>
    <ol className="report-chart" aria-label={title}>
      {points.map((point, index) => {
        const count = point[measure] || 0;
        return <li key={point.date} aria-label={shortDate(point.date) + ", " + number(count)}
          title={shortDate(point.date) + (interval > 1 ? " week · " : " · ") + number(count)}>
          <span className="activity-track">
            {points.length <= 7 && <b style={{bottom: `${count / max * 83}%`}}>{count}</b>}
            <i style={{height: `${count / max * 83}%`}} />
          </span>
          <time dateTime={point.date}>{index === 0 || points.length <= 7 || index === points.length - 1
            ? point.date.slice(-2).replace(/^0/, "") : ""}</time>
        </li>;
      })}
    </ol>
    <div className="activity-axis"><span>{shortDate(points[0].date)}</span>
      <span>{interval === 1 ? "Daily" : "Weekly"}</span><span>{shortDate(points[points.length - 1].date)}</span></div></>}
  </section>;
}

function Breakdown({title, rows}: {title: string; rows: [string, number][]}) {
  const max = Math.max(1, ...rows.map(([, count]) => count));
  return <section className="analytics-panel">
    <div className="panel-heading"><h2>{title}</h2></div>
    {rows.length ? <dl className="pipeline-chart">{rows.map(([label, count], index) =>
      <div key={index}><dt>{label}<span className="source-track"><i style={{width: `${count / max * 100}%`}} /></span></dt>
        <dd>{number(count)}</dd></div>)}</dl> : <p className="muted">No applications in this period.</p>}
  </section>;
}

export function Analytics({sourceName, openSource, sample}: {
  sourceName: (id: string) => string;
  openSource: (id: string) => void;
  sample?: {overview: OverviewStats; report: (end: string, days: number) => AnalyticsReport};
}) {
  const today = dateKey(new Date());
  const [days, setDays] = useState(7);
  const [through, setThrough] = useState("");
  const [tab, setTab] = useState<"applications" | "discovery" | "codex">("applications");
  const [measure, setMeasure] = useState<Measure>("applied");
  const [family, setFamily] = useState("");
  const [usageMeasure, setUsageMeasure] = useState<Measure>("requests");
  const [liveReport, setReport] = useState<AnalyticsReport>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const overview = useOverviewStats(true, sample?.overview);
  const end = through || today;
  const report = sample ? sample.report(end, days) : liveReport;
  useEffect(() => {
    if (sample) return;
    const controller = new AbortController();
    const query = new URLSearchParams({days: String(days), end, zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      offset_minutes: String(-new Date().getTimezoneOffset())});
    const load = () => api<AnalyticsReport>("/api/owner/analytics?" + query, "GET", undefined, controller.signal)
      .then(value => {
        if (!value?.applications || !value?.codex) throw new Error("The Analytics report is unavailable.");
        setReport(value); setError("");
      })
      .catch(error => {
        if (!controller.signal.aborted) setError(error instanceof SyntaxError ? "The Analytics report is unavailable." : error.message);
      });
    setError(""); setReport(undefined);
    void load();
    const timer = window.setInterval(load, 60000);
    return () => {controller.abort(); window.clearInterval(timer);};
  }, [days, end, retry, sample]);
  const app = report?.applications;
  const codex = report?.codex;
  const submitted = app?.current.applied || 0;
  const families = app?.family_series ?? {};
  const trends = families[family] ?? app?.series ?? [];
  const rate = (count: number) => submitted ? `${(count * 100 / submitted).toFixed(1)}%` : "—";
  return <section className="desk-page report-page">
    <PageHeader title="Analytics" context={tab !== "discovery" ? shortDate(moveDate(end, 1 - days)) + " – " + shortDate(end) : undefined}>
      {tab !== "discovery" &&
      <div className="report-controls">
        <button aria-label="Previous period" disabled={end <= "2000-01-01"}
          onClick={() => {
            const previous = moveDate(end, -days);
            setThrough(previous < "2000-01-01" ? "2000-01-01" : previous);
          }}><ChevronLeft size={16} /></button>
        <select aria-label="Period length" value={days} onChange={e => {setDays(Number(e.target.value)); setThrough("");}}>
          <option value="7">7 days</option><option value="28">28 days</option><option value="90">90 days</option><option value="365">1 year</option>
        </select>
        <button aria-label="Next period" disabled={end >= today} onClick={() => {
          const next = moveDate(end, days); setThrough(next >= today ? "" : next);
        }}><ChevronRight size={16} /></button>
        <input type="date" aria-label="Period end" value={end} min="2000-01-01" max={today}
          onChange={e => {if (e.target.validity.valid) setThrough(e.target.value);}} />
      </div>}
    </PageHeader>
    <div className="segmented report-tabs" role="group" aria-label="Analytics category">
      <button aria-pressed={tab === "applications"} onClick={() => setTab("applications")}>Applications</button>
      <button aria-pressed={tab === "discovery"} onClick={() => setTab("discovery")}>Discovery</button>
      <button aria-pressed={tab === "codex"} onClick={() => setTab("codex")}>Tern AI usage</button>
    </div>
    {tab !== "codex" && overview.stats && <CatalogMetrics totals={overview.stats.totals} />}
    {tab === "discovery" && (overview.stats
      ? <DiscoveryPanels stats={overview.stats} owner sourceName={sourceName} openSource={openSource} />
      : <p role={overview.error ? "alert" : "status"}>{overview.error || "Loading discovery…"}</p>)}
    {tab !== "discovery" && error && <div className="notice report-error" role="alert">
      <span>{error}</span><button onClick={() => setRetry(value => value + 1)}>Retry</button></div>}
    {tab !== "discovery" && !report && !error && <p role="status">Loading analytics…</p>}
    {tab === "applications" && app && <>
      <div className="metrics report-metrics">{applicationMeasures.map(([key, label]) => {
        const change = (app.current[key] || 0) - (app.previous[key] || 0);
        return <div key={key}><span>{label}</span><strong>{number(app.current[key] || 0)}</strong>
          <small>{change > 0 ? "+" : ""}{number(change)} vs previous period</small></div>;
      })}</div>
      <div className="analytics-grid">
        <Trend title="Application activity" points={trends} measure={measure} interval={app.interval}
          controls={<div className="report-controls"><select aria-label="Chart metric" value={measure} onChange={e => setMeasure(e.target.value as Measure)}>
            {applicationMeasures.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>{Object.keys(families).length > 0 && <select aria-label="Trend role family" value={families[family] ? family : ""} onChange={e => setFamily(e.target.value)}>
            <option value="">All role families</option>
            {Object.keys(families).map(name => <option key={name}>{name}</option>)}
          </select>}</div>} />
        <Trend title="Active applications" points={trends} measure="active" interval={app.interval} />
        <section className="analytics-panel"><div className="panel-heading"><h2>Outcomes for applications sent in this period</h2></div>
          <dl className="pipeline-chart">
            <div><dt>Reached interview</dt><dd>{rate(app.cohort_interviews)}</dd></div>
            <div><dt>Reached offer</dt><dd>{rate(app.cohort_offers)}</dd></div>
            <div><dt>Median time to first recorded outcome</dt><dd>{app.median_response_days == null ? "—" : `${app.median_response_days} days`}</dd></div>
          </dl>
        </section>
        <Breakdown title="Current pipeline" rows={Object.entries(app.pipeline).map(([key, count]) => [key, count || 0])} />
        <Breakdown title="Most applied-to employers" rows={app.employers} />
        <Breakdown title="Application sources" rows={app.sources.map(([id, count]) => [sourceName(id), count])} />
      </div>
      <section className="analytics-panel"><div className="panel-heading"><h2>Outcomes by role family</h2></div>
        <div className="report-table"><table><thead><tr><th>Role family</th>{applicationMeasures.map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead>
          <tbody>{app.families.map(row => <tr key={row.name}><th scope="row">{row.name}</th>
            {applicationMeasures.map(([key]) => <td key={key}>{number(row[key] || 0)}</td>)}</tr>)}</tbody></table></div>
        {!app.families.length && <p className="muted">No role-family activity in this period.</p>}
      </section>
    </>}
    {tab === "codex" && codex && <>
      <div className="metrics report-metrics">
        {([["requests", "Requests"], ["completed", "Completed"], ["failed", "Failed"], ["limited", "Rate limited"],
          ["input_tokens", "Input tokens"], ["cached_input_tokens", "Cached input tokens"], ["output_tokens", "Output tokens"]] as const)
          .map(([key, label]) => <div key={key}><span>{label}</span>
            <strong>{key.endsWith("_tokens") && !codex.totals.reported ? "—" : number(codex.totals[key] || 0)}</strong></div>)}
      </div>
      <div className="analytics-grid">
        <Trend title="Tern activity" points={codex.series} measure={usageMeasure} interval={app?.interval || 1}
          controls={<select aria-label="Usage chart metric" value={usageMeasure} onChange={e => setUsageMeasure(e.target.value as Measure)}>
            <option value="requests">Requests</option><option value="input_tokens">Input tokens</option>
            <option value="output_tokens">Output tokens</option><option value="failed">Failed requests</option>
          </select>} />
        <section className="analytics-panel"><div className="panel-heading"><h2>Codex account limits</h2></div>
          <CodexUsage usage={report?.usage} />
        </section>
      </div>
      <section className="analytics-panel"><div className="panel-heading"><h2>Usage by task</h2>
        <span>{number(codex.totals.reported || 0)} requests reported tokens</span></div>
        <div className="report-table"><table><thead><tr><th>Task</th><th>Requests</th><th>Input tokens</th><th>Output tokens</th><th>Average duration</th></tr></thead>
          <tbody>{codex.kinds.map(row => <tr key={row.name}><th scope="row">{kindLabels[row.name] || row.name}</th>
            <td>{number(row.requests || 0)}</td><td>{row.reported ? number(row.input_tokens || 0) : "—"}</td>
            <td>{row.reported ? number(row.output_tokens || 0) : "—"}</td>
            <td>{Math.round((row.duration_ms || 0) / (row.requests || 1) / 1000)}s</td></tr>)}</tbody></table></div>
        {!codex.kinds.length && <p className="muted">Tern recorded no Codex requests in this period.</p>}
        <p className="muted">Cached input is included in input tokens. Account limits include Codex activity outside Tern.</p>
      </section>
    </>}
  </section>;
}
