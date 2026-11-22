import {useMemo, useState} from "react";
import {Analytics, dateKey, moveDate, type AnalyticsReport} from "./Analytics";
import {Overview, type OverviewStats} from "./Overview";
import {PageHeader} from "./PageHeader";

const sources: Record<string, string> = {employers: "Employer boards", indeed: "Indeed", lists: "Internship collections"};
const sourceName = (id: string) => sources[id] ?? id;
const roles = [
  {title: "Mechanical Design Co-op", company: "Harbour Robotics", location: "Vancouver, BC", stage: "ready",
    source: "employers", description: "Design fixtures and test assemblies for a new generation of warehouse robots. Work with the mechanical team on CAD, drawings, and prototype validation."},
  {title: "Hardware Test Intern", company: "Clearwater Instruments", location: "Burnaby, BC", stage: "interview",
    source: "indeed", description: "Build bench tests for sensor boards, automate measurements, and investigate failures with the electrical team."},
  {title: "Manufacturing Engineering Intern", company: "Northline Motion", location: "Seattle, WA", stage: "applied",
    source: "lists", description: "Improve tooling and document the assembly process for compact electromechanical products."},
  {title: "Robotics Software Intern", company: "Harbour Robotics", location: "Vancouver, BC", stage: "shortlisted",
    source: "employers", description: "Develop and test motion software for a mobile robot fleet. Use Python and C++ to analyze test runs."},
  {title: "Product Design Intern", company: "Northline Motion", location: "Seattle, WA", stage: "offer",
    source: "employers", description: "Prototype mechanical assemblies, evaluate tolerances, and work with suppliers on design changes."},
] as const;

function demoData(today: string) {
  const discovered = [6, 12, 5, 14, 11, 8, 10, 9, 15, 5, 8, 12, 7, 4];
  const applied = [1, 0, 2, 0, 1, 1, 0, 2, 1, 0, 1, 2, 1, 0];
  const activity = Array.from({length: 14}, (_, index) => ({
    date: moveDate(today, index - 13), applied: applied[index], interview: Number(index === 5 || index === 12),
    offer: Number(index === 11), closed: Number(index === 8), assessment: Number(index === 10), active: 3 + Math.floor(index / 2),
  }));
  const pipeline = {shortlisted: 4, preparing: 1, ready: 2, applied: 7, interview: 2, offer: 1, closed: 3};
  const overview: OverviewStats = {
    totals: {openings: 186, employers: 72, week: discovered.slice(-7).reduce((sum, value) => sum + value, 0)},
    sources: [{source: "employers", count: 112}, {source: "indeed", count: 46}, {source: "lists", count: 28}],
    added: activity.map(({date}, index) => ({date, count: discovered[index]})),
    submitted: activity.map(({date, applied}) => ({date, count: applied})),
    pipeline: Object.entries(pipeline).map(([status, count]) => ({status, count})),
  };
  const fields = ["applied", "interview", "offer", "closed", "assessment"] as const;
  const sum = (rows: typeof activity) => Object.fromEntries(fields.map(key =>
    [key, rows.reduce((total, row) => total + row[key], 0)])) as Record<typeof fields[number], number>;
  function report(end: string, days: number): AnalyticsReport {
    const start = moveDate(end, 1 - days);
    const prior = moveDate(start, -days);
    const period = activity.filter(row => row.date >= start && row.date <= end);
    const interval = days > 28 ? 7 : 1;
    const series = Array.from({length: Math.ceil(days / interval)}, (_, index) => {
      const date = moveDate(start, index * interval);
      const rows = period.filter(row => row.date >= date && row.date < moveDate(date, interval));
      return {date, ...sum(rows), active: rows.at(-1)?.active ?? 0};
    });
    const calls = series.map(point => {
      const requests = (point.applied ?? 0) + (point.interview ?? 0);
      return {date: point.date, requests, input_tokens: requests * 2180, output_tokens: requests * 410};
    });
    const requests = calls.reduce((total, row) => total + row.requests, 0);
    const totals = {requests, completed: requests, reported: requests, input_tokens: requests * 2180,
      cached_input_tokens: requests * 600, output_tokens: requests * 410, duration_ms: requests * 14000};
    const current = sum(period);
    return {applications: {start, end, interval, series, current, pipeline,
      previous: sum(activity.filter(row => row.date >= prior && row.date < start)),
      families: period.length ? [{name: "Engineering", ...current}] : [],
      family_series: period.length ? {Engineering: series} : {},
      employers: [], sources: [],
      cohort_interviews: current.interview || 0, cohort_offers: current.offer || 0,
      median_response_days: current.interview ? 3 : null},
    codex: {totals, series: calls, kinds: requests ? [{name: "screening", ...totals}] : []},
    usage: {available: 1, checked: new Date().toISOString(), pause_until: null,
      windows: [{used: 18, minutes: 300, resets: null}, {used: 36, minutes: 10080, resets: null}]}};
  }
  return {overview, report};
}

export function Demo({exit}: {exit: () => void}) {
  const today = dateKey(new Date());
  const sample = useMemo(() => demoData(today), [today]);
  const [view, setView] = useState<"Overview" | "Openings" | "Analytics">("Overview");
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState("");
  const role = roles.find(item => item.title === selected);
  function browse(source = "", title = "") {
    setFilter(source); setSelected(title); setView("Openings");
  }
  return <div className="desk-page demo-page">
    <div className="demo-toolbar">
      <span><strong>Demo mode</strong><small>Sample data</small></span>
      <div className="segmented" role="group" aria-label="Demo views">
        {(["Overview", "Openings", "Analytics"] as const).map(tab => <button key={tab} aria-pressed={view === tab}
          onClick={() => tab === "Openings" ? browse() : setView(tab)}>{tab}</button>)}
      </div>
      <button onClick={exit}>Exit demo</button>
    </div>
    {view === "Overview" && <Overview name="Alex" owner sourceName={sourceName} openSource={browse}
      openCatalog={() => browse()} openPriority={(_target, id) => browse("", id)}
      tasks={[{label: "Ready to submit", value: 2, open: () => browse("", roles[0].title)},
        {label: "Due or overdue", value: 1, open: () => browse("", roles[1].title)},
        {label: "New matches", value: 4, open: () => browse()}]}
      sample={{stats: sample.overview, priorities: [{view: "Materials", id: roles[0].title,
        label: "PDFs ready", title: roles[0].title}, {view: "Replies", id: roles[1].title,
        label: "Interview invitation", title: roles[1].title}]}} />}
    {view === "Analytics" && <Analytics sourceName={sourceName} openSource={browse} sample={sample} />}
    {view === "Openings" && <>
      <PageHeader title="Sample openings">{filter && <button onClick={() => browse()}>Clear source filter</button>}</PageHeader>
      <div className="analytics-grid demo-openings">
        <section className="analytics-panel" aria-label="Openings">
          {roles.filter(item => !filter || item.source === filter).map(item =>
            <button className="attention-row" key={item.title} aria-pressed={selected === item.title}
              onClick={() => setSelected(selected === item.title ? "" : item.title)}>
              <strong>{item.title}</strong><span>{item.company} · {item.location}</span>
            </button>)}
        </section>
        {role && <section className="analytics-panel" aria-label="Posting details">
          <div className="panel-heading"><h2>{role.title}</h2></div>
          <p className="muted">{role.company} · {role.location} · {sourceName(role.source)}</p>
          <p>{role.description}</p><p className="muted">Stage · {role.stage}</p>
        </section>}
      </div>
    </>}
  </div>;
}
