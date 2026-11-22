import {PageHeader} from "./PageHeader";
import {useEffect, useState} from "react";
import {api} from "./api";
import {CodexUsage} from "./Analytics";
import type {ComponentProps} from "react";

type Attention = {view:"Replies"|"Referrals"|"Materials"; id:string; label:string; title:string; due?:string; company?:string};
type BackgroundState = {
  worker: {status:string} | null;
  usage: ComponentProps<typeof CodexUsage>["usage"];
  collection: {interval_minutes:number; requested:number; started?:string; finished?:string; error?:string} | null;
  tasks: {id:string; status:string; title:string; company:string; job_id:string}[];
};

export function NeedsYou({open}:{open:(view:Attention["view"],id:string,company?:string)=>void}) {
  const [items,setItems] = useState<Attention[]>();
  const [message,setMessage] = useState("");
  useEffect(()=>{
    const refresh=()=>api<Attention[]>("/api/owner/priorities?limit=100").then(setItems).catch(error=>setMessage(error.message));
    void refresh();
    const timer=window.setInterval(refresh,15000);
    return ()=>window.clearInterval(timer);
  },[]);
  return <section className="desk-page">
    <PageHeader title="Needs you" />
    {message && <p role="alert">{message}</p>}
    {items?.length===0 && <p>Nothing needs your attention right now.</p>}
    {items===undefined && !message && <p role="status">Loading…</p>}
    {items?.map(item=><button className="attention-row" key={item.view+item.id+item.label} onClick={()=>open(item.view,item.id,item.company)}>
      <strong>{item.title}</strong><span>{item.label}{item.due && " · "+new Date(item.due).toLocaleString()}</span>
    </button>)}
  </section>;
}

export function Background({open}:{open:(id:string)=>void}) {
  const [data,setData] = useState<BackgroundState>();
  const [message,setMessage] = useState("");
  const [busy,setBusy] = useState(false);
  const load=()=>api<BackgroundState>("/api/owner/background").then(setData);
  useEffect(()=>{
    const refresh=()=>load().catch(error=>setMessage(error.message));
    void refresh();
    const timer=window.setInterval(refresh,5000);
    return ()=>window.clearInterval(timer);
  },[]);
  async function update(path:string, method:string, done:string) {
    setBusy(true);
    try {await api(path,method); await load(); setMessage(done);}
    catch(error){setMessage((error as Error).message);}
    finally{setBusy(false);}
  }
  const collection=data?.collection;
  return <section className="desk-page">
    <PageHeader title="Background work">
      <button className="primary" disabled={busy || !!collection?.requested} onClick={()=>void update("/api/owner/background/run","POST","Source check requested.")}>Check due sources now</button>
    </PageHeader>
    <section className="desk-card">
      <h2>Source checks</h2>
      <p>{collection?.requested?"Queued":collection?.started&&!collection?.finished?"Running":collection?.finished?"Last finished "+new Date(collection.finished).toLocaleString():"Waiting for worker"}{collection?.error&&" · "+collection.error}</p>
      {data && <form onSubmit={event=>{
        event.preventDefault();
        const minutes=new FormData(event.currentTarget).get("minutes");
        void update("/api/owner/background/schedule?minutes="+encodeURIComponent(String(minutes)),"PUT","Schedule saved.");
      }}>
        <label>Check interval in minutes<input key={collection?.interval_minutes} type="number" name="minutes" min={5} max={1440} required defaultValue={collection?.interval_minutes ?? 5}/></label>
        <button disabled={busy}>Save interval</button>
      </form>}
    </section>
    <section className="desk-card"><h2>Codex work</h2>
      <p>{data?.worker?.status==="connected"?"Connected":"Check your Codex connection in Settings."}</p>
      {data?.worker?.status==="connected" && <CodexUsage usage={data.usage}/>}
      {data?.tasks.length===0 && <p>No Codex tasks yet.</p>}
      {data?.tasks.map(task=><button className="attention-row" key={task.id} onClick={()=>open(task.job_id)}>
        <strong>{task.title} · {task.company}</strong><span>{task.status==="limited"?"Paused by usage limit":task.status}</span>
      </button>)}
    </section>
    {message && <p role="status">{message}</p>}
  </section>;
}
