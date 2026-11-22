import {CodexHint} from "./CodexConnection";
import {BriefcaseBusiness} from "lucide-react";
import {PageHeader} from "./PageHeader";
import {useEffect, useRef, useState} from "react";
import {api, type Application} from "./api";

type Prefs = {auto_shortlist:boolean; draft:boolean; threshold:number;smart:boolean;prepare:boolean;max_experience_years:number;reject_no_sponsorship:boolean;minimum_annual_pay:number};
type Screen = {reviews:{id:string;title:string;company:string;verdict:"apply"|"review"|"skip";score:number|null;summary:string}[];preferences:Prefs; roles:{id:string;title:string;company:string;location:string;score:number;reasons:string[]}[]};
export function Screening({open, settings, materials, codexReady, connectCodex}: {codexReady: boolean; connectCodex: () => void; materials:(id:string)=>void;open:(id:string)=>void; settings:()=>void}) {
  const preferencesDialog = useRef<HTMLDialogElement>(null);
  const [preferencesError, setPreferencesError] = useState("");
  const [data,setData] = useState<Screen>();
  const [error,setError] = useState("");
  const [busy,setBusy] = useState(false);
  const load = () => api<Screen>("/api/owner/screening").then(setData);
  useEffect(()=>{
    const refresh=()=>load().catch(e=>setError(e.message));
    void refresh();
    const timer=window.setInterval(refresh,15000);
    return ()=>window.clearInterval(timer);
  },[]);
  async function save(e:React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form=new FormData(e.currentTarget);
    setBusy(true);
    setPreferencesError("");
    try {
      await api("/api/owner/screening","PUT",{auto_shortlist:form.has("auto"),draft:codexReady ? form.has("draft") : data?.preferences.draft ?? false,threshold:Number(form.get("threshold")),smart:codexReady ? form.has("smart") : data?.preferences.smart ?? false,prepare:codexReady ? form.has("prepare") : data?.preferences.prepare ?? false,
        max_experience_years:Number(form.get("experience")),reject_no_sponsorship:form.has("sponsorship"),minimum_annual_pay:Number(form.get("annualPay"))});
      await load();
      preferencesDialog.current?.close();
      setError("Preferences saved.");
    } catch(e){setPreferencesError((e as Error).message);} finally {setBusy(false);}
  }
  return <section className="screening-page">
    <PageHeader title="Where to apply" />
    <div className="jobs-toolbar">
      <button onClick={settings}>Edit saved searches</button>
      <button disabled={!data} onClick={() => {
        setPreferencesError("");
        preferencesDialog.current?.querySelector("form")?.reset();
        preferencesDialog.current?.showModal();
      }}>Screening preferences</button>
    </div>
    <p role="status" className="feedback">{error || (!data ? "Loading recommendations…" : "")}</p>
    {data && <><dialog ref={preferencesDialog} className="screening-settings" aria-labelledby="screening-heading">
      <h2 id="screening-heading">Screening preferences</h2>
      <form onSubmit={save}>
      <label className="checkbox"><input name="auto" type="checkbox" defaultChecked={data.preferences.auto_shortlist}/> Save qualifying roles</label>
      <label>Minimum score out of 100<input name="threshold" type="number" min="50" max="100" required defaultValue={data.preferences.threshold}/></label>
      <label className="checkbox"><input name="draft" type="checkbox" disabled={!codexReady} defaultChecked={data.preferences.draft}/> Queue a Codex review and cover letter for each new shortlist match</label>
      <label className="checkbox"><input name="smart" type="checkbox" disabled={!codexReady} defaultChecked={data.preferences.smart}/> Screen shortlisted roles with Codex for a fit score and verdict</label>
      <label className="checkbox"><input name="prepare" type="checkbox" disabled={!codexReady} defaultChecked={data.preferences.prepare}/> Build and check both PDFs for strong Apply verdicts</label>
      {!codexReady && <CodexHint connect={() => {preferencesDialog.current?.close(); connectCodex();}} />}
      <label>Maximum experience required (0 for any)<input name="experience" type="number" min="0" max="20" defaultValue={data.preferences.max_experience_years}/></label>
      <label className="checkbox"><input name="sponsorship" type="checkbox" defaultChecked={data.preferences.reject_no_sponsorship}/> Exclude explicit no-sponsorship and citizenship-only postings during screening</label>
      <label>Minimum listed annual pay (0 for any)<input name="annualPay" type="number" min="0" max="1000000" defaultValue={data.preferences.minimum_annual_pay}/></label>
      {preferencesError && <p role="alert">{preferencesError}</p>}
      <div className="screening-actions">
        <button type="button" onClick={() => preferencesDialog.current?.close()}>Close</button>
        <button className="primary" disabled={busy}>Save preferences</button>
      </div>
      </form></dialog>
      {!!data.reviews?.length && <section className="job-results">
        <div className="feed-head"><h2>Screened roles</h2><span>Verdict</span></div>
        {data.reviews.map(review => <button className="job" key={review.id} onClick={() => materials(review.id)}>
          <BriefcaseBusiness className="job-icon" size={17} aria-hidden="true" />
          <span className="job-copy"><strong>{review.title}</strong><span>{review.company}{review.summary && " · " + review.summary}</span></span>
          <span className="row-meta">{{apply:"Apply",review:"Apply with risk",skip:"Skip"}[review.verdict]}{review.score != null && " · " + review.score + "/100"}</span>
        </button>)}
      </section>}
      <section className="job-results">
        <div className="feed-head"><h2>Recommended openings</h2><span>Match</span></div>
        {!data.roles.length && <div className="empty">
          <strong>No matching openings</strong><p>Adjust your saved searches or watchlist to see more roles from the last 30 days.</p>
        </div>}
        {data.roles.map(role => <button key={role.id} className="job" onClick={() => open(role.id)}>
          <BriefcaseBusiness className="job-icon" size={17} aria-hidden="true" />
          <span className="job-copy"><strong>{role.title}</strong><span>{[role.company, role.location, ...role.reasons].filter(Boolean).join(" · ")}</span></span>
          <span className="row-meta">{role.score}/100</span>
        </button>)}
      </section>
    </>}
  </section>;
}

type Reply={id:number;subject:string;sender:string;body:string;kind:string;applied:number;application_id:string;due:string|null;link:string;done:number};
function localDate(value:string|null) {
  if(!value) return "";
  const d=new Date(value);
  return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);
}
function ReplyCard({item,apps,saved,focus}: {focus:string;item:Reply;apps:Application[];saved:()=>Promise<void>}) {
  const [message,setMessage]=useState("");
  const remaining=item.due ? Date.parse(item.due)-Date.now() : Infinity;
  async function update(e:React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form=new FormData(e.currentTarget);
    try {
      await api("/api/owner/replies/"+item.id,"PUT",{kind:form.get("kind"),application_id:form.get("application"),link:form.get("link"),
        due:form.get("due") ? new Date(String(form.get("due"))).toISOString():null, done:form.has("done")});
      await saved(); setMessage("Saved.");
    } catch(e){setMessage(String(e));}
  }
  return <details open={String(item.id)===focus||undefined} className="desk-card"><summary><strong>{item.subject}</strong> · {item.kind} {item.done ? "· Done" : remaining<0 ? "· Overdue" : remaining<=86400000 ? "· Due within 24 hours" : ""}
    {item.due && " · "+new Date(item.due).toLocaleString()}</summary><p>{item.sender}</p><p style={{whiteSpace:"pre-wrap"}}>{item.body}</p>
    <form onSubmit={update}><label>Outcome<select name="kind" defaultValue={item.kind}>{["Reply","Confirmation","Assessment","Interview","Offer","Rejected"].map(k=><option key={k}>{k}</option>)}</select></label><label>Application<select name="application" defaultValue={item.application_id}><option value="">Unassigned</option>
    {apps.map(a=><option key={a.id} value={a.id}>{a.company} · {a.title}</option>)}</select></label>
    <label>Deadline (your local time)<input type="datetime-local" name="due" defaultValue={localDate(item.due)}/></label>
    <label>Assessment or meeting link<input type="url" name="link" defaultValue={item.link}/></label>
    {item.link && <a href={item.link} target="_blank" rel="noreferrer">Open appointment or assessment</a>}
    <label className="checkbox"><input type="checkbox" name="done" defaultChecked={!!item.done}/> Done</label>
    <button>Save reply</button></form>
    {(item.applied || (item.application_id && ["Confirmation","Interview","Offer","Rejected"].includes(item.kind))) ? <button onClick={async()=>{
      try{await api("/api/owner/replies/"+item.id+"/outcome?undo="+Boolean(item.applied),"POST");await saved();setMessage("Stage updated.");}
      catch(e){setMessage(String(e));}
    }}>{item.applied ? "Undo stage change" : "Update application to "+({Confirmation:"applied",Interview:"interview",Offer:"offer",Rejected:"closed"}[item.kind])}</button> : null}<p role="status">{message}</p></details>;
}
export function Replies({apps,connect,focus,notifications}:{notifications:{enabled:boolean;supported:boolean;toggle:()=>Promise<void>};focus:string;apps:Application[];connect:()=>void}) {
  const [data,setData]=useState<{items:Reply[];mail:boolean;sync?:{status:string;checked:string}}>();
  const [error,setError]=useState("");
  const load=()=>api<{items:Reply[];mail:boolean;sync?:{status:string;checked:string}}>("/api/owner/replies").then(setData);
  useEffect(()=>{const check=()=>load().catch(e=>setError(e.message)); void check();
    const timer=setInterval(check,30000); return ()=>clearInterval(timer);},[]);
  const hasReplies = Boolean(data?.items.length);
  return <section className="settings">
    <PageHeader title="Email & deadlines">
      {(data?.mail || hasReplies) && notifications.supported && <button aria-pressed={notifications.enabled}
        onClick={()=>void notifications.toggle().catch(error=>setError(error.message))}>
        {notifications.enabled?"Turn off desktop reminders":"Enable desktop reminders"}
      </button>}
      {(data?.mail || hasReplies) && <button onClick={connect}>Manage inboxes</button>}
    </PageHeader>
    {!data && !error && <p role="status">Loading inbox…</p>}
    {data && !data.mail && !hasReplies && <section className="desk-card">
      <h2>Connect your inbox</h2>
      <p>Connect Gmail or Outlook to see employer replies and assessment deadlines here.</p>
      <button className="primary" onClick={connect}>Connect an inbox</button>
    </section>}
    {data?.mail && <p className="muted">{data.sync ? data.sync.status+" · "+new Date(data.sync.checked).toLocaleString() : "Waiting for first mailbox check."}</p>}
    {data?.mail && !hasReplies && <p>No employer replies yet.</p>}
    {data?.items.map(item => <ReplyCard focus={focus} key={item.id} item={item} apps={apps} saved={load}/>)}
    {error && <p role="alert">{error}</p>}
  </section>;
}
