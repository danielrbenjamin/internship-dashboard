import {PageHeader} from "./PageHeader";
import {useEffect, useState} from "react";
import {api, statuses} from "./api";

type Day = {date: string; count: number};
export type OverviewStats = {
  totals: {openings: number; employers: number; week: number};
  added: Day[];
  sources: {source: string; count: number}[];
  submitted?: Day[];
  pipeline?: {status: string; count: number}[];
};
const number = (value: number) => value.toLocaleString();
const dateLabel = (value: string) => new Intl.DateTimeFormat(undefined, {month: "short", day: "numeric"})
  .format(new Date(value + "T12:00:00"));

function Activity({days, series, title}: {days: string[]; series: Day[]; title: string}) {
  const byDate = new Map(series.map(day => [day.date, day.count]));
  const max = Math.max(1, ...series.map(day => day.count));
  return <section className="analytics-panel">
    <div className="panel-heading"><h2>{title}</h2><span>Last 14 days</span></div>
    <ol className="activity-chart">
      {days.map(day => {
        const amount = byDate.get(day) || 0;
        const label = `${dateLabel(day)}: ${number(amount)}`;
        return <li key={day} aria-label={label} title={label}>
          <span className="activity-track"><i style={{height: `${amount * 100 / max}%`}} /></span>
          <time dateTime={day}>{day.slice(8).replace(/^0/, "")}</time>
        </li>;
      })}
    </ol>
    <div className="activity-axis"><span>{dateLabel(days[0])}</span><span>{dateLabel(days[days.length - 1])}</span></div>
  </section>;
}

export function useOverviewStats(owner: boolean, sample?: OverviewStats) {
  const [stats, setStats] = useState<OverviewStats>();
  const [error, setError] = useState("");
  useEffect(() => {
    if (sample) return;
    const controller = new AbortController();
    const url = "/api/analytics?offset_minutes=" + -new Date().getTimezoneOffset();
    const load = () => void api<OverviewStats>(url, "GET", undefined, controller.signal).then(value => {
      setError(""); setStats(value);
    })
      .catch(() => {if (!controller.signal.aborted) setError("Analytics could not be loaded.");});
    load();
    const timer = window.setInterval(load, 60000);
    return () => {controller.abort(); window.clearInterval(timer);};
  }, [owner, sample]);
  return {stats: sample ?? stats, error};
}

export function CatalogMetrics({totals}: {totals: OverviewStats["totals"]}) {
  return <div className="metrics">
    {[[totals.openings, "Active openings"], [totals.employers, "Employers"],
      [totals.week, "Active roles added in last 7 days"]].map(([value, label]) =>
      <div key={label}><span>{label}</span><strong>{number(Number(value))}</strong></div>)}
  </div>;
}

export function DiscoveryPanels({stats, owner, sourceName, openSource}: {
  stats: OverviewStats; owner: boolean; sourceName: (id: string) => string; openSource: (id: string) => void;
}) {
  const days = Array.from({length: 14}, (_, index) => {
    const day = new Date();
    day.setDate(day.getDate() - (13 - index));
    return [day.getFullYear(), day.getMonth() + 1, day.getDate()].map(part => String(part).padStart(2, "0")).join("-");
  });
  const pipeline = new Map(stats.pipeline?.map(row => [row.status, row.count]));
  return <div className="analytics-grid">
        <Activity days={days} series={stats.added} title="Newly discovered roles" />
        <section className="analytics-panel"><div className="panel-heading"><h2>Top sources by openings</h2></div>
          <ul className="source-chart">
            {stats.sources.slice(0,10).map(source => <li key={source.source}>
              <button onClick={() => openSource(source.source)}>
                <span>{sourceName(source.source)}</span><strong>{number(source.count)}</strong>
                <span className="source-track"><i style={{width: `${source.count / (stats.sources[0]?.count || 1) * 100}%`}} /></span>
              </button>
            </li>)}
          </ul>
          {!stats.sources.length && <p className="muted">Collection has yet to add a posting.</p>}
        </section>
        {owner && stats.pipeline && <>
          <section className="analytics-panel"><div className="panel-heading"><h2>Application pipeline</h2></div>
            <dl className="pipeline-chart">{statuses.map(status =>
              <div key={status}><dt>{status}</dt><dd>{number(pipeline.get(status) || 0)}</dd></div>)}</dl>
          </section>
          <Activity days={days} series={stats.submitted || []} title="Applications recorded as applied" />
        </>}
      </div>;
}

type Priority = {id:string;view:"Replies"|"Referrals"|"Materials";label:string;title:string;due?:string;company?:string};

export function Overview({name,tasks,openPriority,owner, sourceName, openSource, openCatalog, sample}: {
  openPriority:(view:Priority["view"],id:string,company?:string)=>void;name?:string;tasks:{label:string;value:number;open:()=>void}[];
  owner: boolean; sourceName: (id: string) => string; openSource: (id: string) => void; openCatalog: () => void;
  sample?: {stats: OverviewStats; priorities: Priority[]};
}) {
  const [livePriorities,setPriorities]=useState<Priority[]>();
  useEffect(()=>{if(!owner || sample)return;const controller=new AbortController();
    const load=()=>api<Priority[]>("/api/owner/priorities","GET",undefined,controller.signal).then(setPriorities).catch(()=>{});
    void load();const timer=setInterval(load,30000);return ()=>{controller.abort();clearInterval(timer)};},[owner,sample]);
  const priorities = sample?.priorities ?? livePriorities;
  const {stats, error} = useOverviewStats(owner, sample?.stats);
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
  return <section className="desk-page">
    <PageHeader title={`Good ${greeting}${name ? ", " + name.trim().split(/\s+/)[0] : ""}`}
      context={new Date().toLocaleDateString(undefined,{weekday:"long",month:"long",day:"numeric"})}>
      <button className="primary" onClick={openCatalog}>Browse openings</button>
    </PageHeader>
    {error ? <p className="notice" role="alert">{error}</p> : !stats ? <p role="status">Loading analytics…</p> : <>
      {tasks.length>0&&<section className="today-actions" aria-label="Application priorities">{tasks.map(t=><button key={t.label} onClick={t.open}><strong>{t.value}</strong><span>{t.label}</span></button>)}</section>}
      <CatalogMetrics totals={stats.totals} />
      {owner&&!!priorities?.length&&<section className="desk-card"><h2>Needs your attention</h2>{priorities.map(p=><button className="attention-row" key={p.view+p.id} onClick={()=>openPriority(p.view,p.id,p.company)}>
      <strong>{p.title}</strong><span>{p.label}{p.due&&" · "+new Date(p.due).toLocaleString()}</span></button>)}</section>}
      <DiscoveryPanels stats={stats} owner={owner} sourceName={sourceName} openSource={openSource} />
    </>}
  </section>;
}
