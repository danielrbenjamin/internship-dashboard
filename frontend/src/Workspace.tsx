import {AIBadge, CodexConnection, CodexHint} from "./CodexConnection";
import {PageHeader} from "./PageHeader";

import {lazy, Suspense, useEffect, useState} from "react";
import {MailSettings} from "./MailSettings";
import {PostingText} from "./PostingText";
import {api, assetHref, formatDate, statuses} from "./api";
import type {Application, Details, Document, Job, Profile, ScoringWeights, Search} from "./api";

const ProjectEditor=lazy(()=>import("./ProjectEditor"));

type Report = {preparation_error?:string; preparation_started?:boolean; prepared_version?:string; material?:"resume"|"cover"; verdict?:"apply"|"review"|"skip"; match_score?:number; recruiter_read?:string;document_id?: string; source_file?: string; interview_questions?:string[]; engineering_fit?: string; assessment?: {field: string; classification: string; requirement: string; quote: string}[];
  edits?: {before: string; after: string}[]; cover_letter?: string};

export function Workspace({job, application, reload, codexReady, connectCodex}: {codexReady: boolean; connectCodex: () => void; job: Job; application?: Application; reload: () => Promise<void>}) {
  const [details, setDetails] = useState<Details>();
  const [status, setStatus] = useState(application?.status || "shortlisted");
  const [notes, setNotes] = useState(application?.notes || "");
  const [deadline, setDeadline] = useState(application?.deadline || "");
  const [selected, setSelected] = useState("");
  const [submitted, setSubmitted] = useState(application?.submitted_version || "");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [material, setMaterial] = useState<"resume" | "cover">("resume");
  const [letter, setLetter] = useState<string>();
  const [letterId, setLetterId] = useState("");
  const base = "/api/owner";
  const route = base + "/applications/" + application?.id;
  const versions = details?.documents.filter(item => (item.kind || "resume") === material) || [];
  const doc = versions.find(item => item.id === selected) || versions[0];
  const pending = details?.ai.some(task => ["running", "queued", "limited"].includes(task.status));
  useEffect(() => { if (application?.status) setStatus(application.status); }, [application?.status]);
  const selectedLetter = details?.cover_letters.find(item => item.id === letterId) || details?.cover_letters[0];
  const workingLetter = letter ?? selectedLetter?.content ?? "";
  useEffect(() => {
    if (!application?.id) return;
    const controller = new AbortController();
    const refresh = () => api<Details>(route, "GET", undefined, controller.signal)
      .then(setDetails).catch(error => { if (!controller.signal.aborted) setMessage(error.message); });
    void refresh();
    const timer = pending ? window.setInterval(refresh, 3500) : undefined;
    return () => {controller.abort(); window.clearInterval(timer);};
  }, [application?.id, route, pending]);

  async function action(fn: () => Promise<unknown>, success: string) {
    setBusy(true);
    setMessage("");
    try {
      await fn();
      await reload();
      if (application) setDetails(await api<Details>(route));
      setMessage(success);
    } catch (error) { setMessage((error as Error).message); }
    finally {setBusy(false);}
  }

  function switchMaterial(next: "resume" | "cover") {
    if (next === material) return;
    setMaterial(next); setSelected("");
  }

  function documentLinks(version: Document) {
    const path = base + "/documents/" + version.id;
    return <div className="actions">
      {version.compiled === 1 && <a className="button" href={assetHref(path + "/pdf")} target="_blank" rel="noreferrer">Open PDF</a>}
      <a className="button" href={assetHref(path + "/zip")} download>Source ZIP</a>
    </div>;
  }

  return <section className="workspace" aria-label="Private application workspace">
    {!!job.matched_skills?.length && <p className="muted">Matched skills · {job.matched_skills.join(", ")}</p>}
    <details className="desk-card" open={!application}><summary>Tracking details</summary>
    <form onSubmit={event => {
      event.preventDefault();
      void action(() => api(base + "/jobs/" + job.id + "/application", "PUT", {
        status, notes, deadline: deadline || null,
        submitted_version: submitted && submitted !== application?.submitted_version ? submitted : null,
      }), "Application saved.");
    }}>
      <div className="fields">
        <div className="field"><label htmlFor="application-status">Status</label>
          <select id="application-status" value={status} onChange={event => setStatus(event.target.value)}>
            {statuses.map(value => <option key={value}>{value}</option>)}
          </select></div>
        <div className="field"><label htmlFor="application-deadline">Deadline</label>
          <input id="application-deadline" type="date" value={deadline} onChange={event => setDeadline(event.target.value)} /></div>
      </div>
      <label>Private notes<textarea rows={3} value={notes} onChange={e => setNotes(e.target.value)} /></label>
      {!!details?.documents.some(item => item.kind !== "cover" && item.compiled) && <div className="field">
        <label htmlFor="submitted-version">Submitted version</label>
        <select id="submitted-version" value={submitted} onChange={e => setSubmitted(e.target.value)}>
          <option value="" disabled={Boolean(application?.submitted_version)}>Choose a compiled version</option>
          {details.documents.filter(item => item.kind !== "cover" && item.compiled).map(item =>
            <option key={item.id} value={item.id}>{formatDate(item.created_at)} · {item.id.slice(0, 8)}</option>)}
        </select>
      </div>}
      <button className="primary" disabled={busy}>{application ? "Save application" : "Add to tracker"}</button>
    </form></details>
    {application && <>
      <div className="document-toolbar"><div className="segmented" role="group" aria-label="Document type">
        <button aria-pressed={material === "resume"} onClick={() => switchMaterial("resume")}>Résumé</button>
        <button aria-pressed={material === "cover"} onClick={() => switchMaterial("cover")}>Cover letter</button>
      </div>
      <div className="actions">
        <button className="primary" disabled={!codexReady || busy || pending || !details?.posting.description}
          onClick={() => action(() => api(route + "/prepare", "POST"), "Both PDFs queued for preparation.")}>Prepare both PDFs <AIBadge /></button>
        <button disabled={busy} onClick={() => action(async () => {
          const result = await api<{id: string}>(route + (material === "resume" ? "/resume" : "/cover-template"), "POST");
          setSelected(result.id);
        }, "GitHub snapshot imported.")}>Import latest from GitHub</button>
        <button disabled={busy} onClick={()=>action(async()=>{const r=await api<{id:string}>(route+"/from-template/"+material,"POST");setSelected(r.id);},"Copied base template.")}>Use my saved template</button>
        {!doc && <button disabled={!codexReady||busy||pending||!details?.posting.description} onClick={()=>action(()=>api(route+"/ai","POST"),"Review queued.")}>Assess eligibility <AIBadge /></button>}
      </div>
      </div>
      {!codexReady && <CodexHint connect={connectCodex} />}
      {details && !details.posting.description &&
        <p className="muted">Open the original posting to review requirements.</p>}
      {doc && <>
        <label>Working version<select value={doc.id} onChange={e => {setSelected(e.target.value);}}>
          {versions.map(item => <option key={item.id} value={item.id}>
            {formatDate(item.created_at)} · {item.id.slice(0, 8)} · {item.verified ? "Passed PDF checks" : "Git " + item.commit_sha.slice(0, 7)}
          </option>)}
        </select></label>
        <Suspense fallback={<p>Opening editor…</p>}><ProjectEditor key={doc.id} doc={doc} tasks={details?.ai||[]} codexReady={codexReady} connectCodex={connectCodex}
          onVersion={async id=>{const updated=await api<Details>(route);setDetails(updated);setSelected(id);}}
          suggest={async file=>{await api(route+"/ai?doc_id="+doc.id+"&source_file="+encodeURIComponent(file),"POST");setDetails(await api<Details>(route));setMessage("Codex review queued.");}}/></Suspense>
        {documentLinks(doc)}
      </>}
      {material === "cover" && <details open={letter !== undefined || undefined}><summary>Plain-text cover letter</summary><section aria-label="Cover letter editor">
        <div className="actions">
          <button disabled={!codexReady || busy || pending || !details?.posting.description} onClick={() => action(
            () => api(route + "/ai?cover_letter=true", "POST"), "Cover letter request queued.")}>Draft with Codex <AIBadge /></button>
          {!!selectedLetter && <>
            <a className="button" href={assetHref(`${route}/cover-letters/${selectedLetter.id}/txt`)} download>Download text</a>
            <a className="button" href={assetHref(`${route}/cover-letters/${selectedLetter.id}/pdf`)} download>Download PDF</a>
          </>}
        </div>
        {!!details?.cover_letters.length && <label>Saved version
          <select value={selectedLetter?.id} onChange={event => {setLetterId(event.target.value); setLetter(undefined);}}>
            {details.cover_letters.map(item => <option key={item.id} value={item.id}>
              {formatDate(item.created_at)} · {item.id.slice(0, 7)}</option>)}
          </select></label>}
        <label>Cover letter text<textarea rows={15} maxLength={12000} value={workingLetter}
          onChange={event => setLetter(event.target.value)} /></label>
        <button className="primary" disabled={busy || !workingLetter.trim() || workingLetter === selectedLetter?.content}
          onClick={() => action(async () => {
            const saved = await api<{id: string}>(route + "/cover-letters", "POST", {content: workingLetter});
            setLetterId(saved.id); setLetter(undefined);
          }, "Cover letter version saved.")}>Save cover letter</button>
      </section></details>}
      {details?.ai.map(task => <TaskResult key={task.id} task={task} onLetter={content => {
        setMaterial("cover"); setLetter(content);
      }} />)}
      {application.submitted_version && <section><h3>Submitted files</h3>
        {documentLinks({id: application.submitted_version, compiled: 1, commit_sha: "", created_at: ""})}</section>}
      <details><summary>Saved posting &amp; history</summary>
        <PostingText text={details?.posting.description || ""} />
        <ul>{details?.history.map((item, i) => <li key={i}>{formatDate(item.at)} · {item.event}</li>)}</ul>
      </details>
    </>}
    <p role="status" className="feedback">{busy ? "Working…" : message}</p>
  </section>;
}

function TaskResult({task, onLetter}: {task: {status: string; result: string};
  onLetter: (content: string) => void}) {
  if (task.status !== "done") return <p className="muted">Codex: {
    ["queued", "running"].includes(task.status) ? task.status : task.result}</p>;
  let report: Report;
  try { report = JSON.parse(task.result); } catch { return <p>Report could not be read.</p>; }
  if (report.preparation_started) return null;
  const material = report.material === "cover" ? "Cover letter" : "Résumé";
  if (report.prepared_version) return <p>{material} PDF passed the one-page and layout checks.</p>;
  if (report.material && report.preparation_error) return <details open><summary>{material} PDF needs review</summary>
    <p role="status">{report.preparation_error}</p></details>;
  if (report.cover_letter) return <details open><summary>Codex cover letter draft</summary>
    <p className="posting">{report.cover_letter}</p>
    <button onClick={() => onLetter(report.cover_letter || "")}>Edit draft</button>
  </details>;
  return <details><summary>{report.match_score!=null ? ({apply:"Apply",review:"Apply with risk",skip:"Skip"}[report.verdict||"review"]+" · "+report.match_score+"/100") : "Eligibility and fit"}</summary>
    {report.preparation_error&&<p role="status">{report.preparation_error}</p>}
    {report.recruiter_read&&<p>{report.recruiter_read}</p>}
    <p>{report.engineering_fit}</p>
    {report.assessment?.map((item, index) => <div key={index} className="requirement">
      <strong>{item.field} · {item.classification}</strong><p>{item.requirement}</p>
      {item.quote && <blockquote>{item.quote}</blockquote>}</div>)}
    {!!report.interview_questions?.length&&<section><h3>Interview practice</h3><ul>{report.interview_questions.map(q=><li key={q}>{q}</li>)}</ul></section>}
  </details>;
}

const blank: Search = {name: "", keywords: "", location: "", term: "", preferred: "", alerts: true};
const defaultWeights: ScoringWeights = {saved_search: 50, watchlist: 50, search_detail: 15, search_detail_cap: 50, skill: 10, skill_cap: 30};
const scoreLabels: Record<keyof ScoringWeights, string> = {
  saved_search: "Saved search match", watchlist: "Watchlisted employer", search_detail: "Each matching search detail",
  search_detail_cap: "Maximum search detail points", skill: "Each matched skill", skill_cap: "Maximum skill points",
};

export function SettingsPanel({profile, save, tab, setTab, codexStatus}: {codexStatus: string; tab: string; setTab: (tab: string) => void; profile: Profile; save: (value: Profile) => Promise<void>}) {
  const [value, setValue] = useState(profile);
  const [watchlist, setWatchlist] = useState(profile.watchlist.join(", "));
  const [skills, setSkills] = useState((profile.skills ?? []).join(", "));
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const update = (index: number, change: Partial<Search>) => setValue({
    ...value, searches: value.searches.map((rule, i) => i === index ? {...rule, ...change} : rule),
  });
  return <section className="settings"><PageHeader title="Settings" />
    <div className="segmented">{["Profile","Discovery","Email inboxes","Codex"].map(t=><button key={t} aria-pressed={tab===t} onClick={()=>setTab(t)}>{t}</button>)}</div>
    {tab==="Email inboxes"?<MailSettings/>:tab==="Codex"?<CodexConnection status={codexStatus}/>:<form onSubmit={async event => {
      event.preventDefault(); setBusy(true); setMessage("");
      try {
        await save({...value, watchlist: watchlist.split(",").map(item => item.trim()).filter(Boolean),
          skills: skills.split(/[,\n]/).map(item => item.trim()).filter(Boolean)});
        setMessage("Settings saved.");
      } catch (error) {setMessage((error as Error).message);}
      finally {setBusy(false);}
    }}>
      {tab==="Discovery"?<><h2>Discovery</h2><label>Watchlist employers<input value={watchlist} onChange={e => setWatchlist(e.target.value)}
        placeholder="Employer names, separated by commas" /></label>
      {value.searches.map((rule, index) => <fieldset key={index}><legend>Saved search {index + 1}</legend>
        {(["name", "keywords", "location", "term", "preferred"] as const).map(key => <label key={key}>
          {key === "keywords" ? "Required keywords (comma-separated alternatives)" : key}
          <input required={key === "name"} value={rule[key]} onChange={e => update(index, {[key]: e.target.value})} />
        </label>)}
        <label className="checkbox"><input type="checkbox" checked={rule.alerts} onChange={e => update(index, {alerts: e.target.checked})} /> In-app alerts</label>
        <button type="button" onClick={() => setValue({...value, searches: value.searches.filter((_, i) => i !== index)})}>Remove search</button>
      </fieldset>)}
      <fieldset><legend>Shortlist scoring</legend><div className="fields">
        {(Object.keys(scoreLabels) as (keyof ScoringWeights)[]).map(key => <label key={key}>{scoreLabels[key]}
          <input type="number" min={0} max={100} required value={value.scoring?.[key] ?? defaultWeights[key]}
            onChange={event => setValue({...value, scoring: {...(value.scoring ?? defaultWeights), [key]: Number(event.target.value)}})} />
        </label>)}
      </div></fieldset>

      </>:<><h2>Skills and experience</h2>
      <label>Skills<textarea rows={3} value={skills} onChange={e => setSkills(e.target.value)}
        placeholder="SolidWorks, FEA, GD&T" aria-describedby="skills-help" /></label>
      <p className="muted" id="skills-help">Separate skills with commas or new lines. Change the points under Discovery → Shortlist scoring.</p>
      <label>Verified experience and eligibility profile<textarea rows={7} value={value.experience}
        onChange={e => setValue({...value, experience: e.target.value})} /></label>
      <h2>Application materials</h2>
      <label>GitHub résumé repository<input placeholder="owner/repository" value={value.resume_repo}
        onChange={e => setValue({...value, resume_repo: e.target.value})} /></label>
      <div className="fields"><label>Branch<input value={value.resume_branch} onChange={e => setValue({...value, resume_branch: e.target.value})} /></label>
        <label>LaTeX entry<input value={value.resume_entry} onChange={e => setValue({...value, resume_entry: e.target.value})} /></label></div>
      <label>GitHub cover-letter repository<input placeholder="danielrbenjamin/cover-letter" value={value.cover_repo||""} onChange={e=>setValue({...value,cover_repo:e.target.value})}/></label>
      <div className="fields"><label>Cover-letter branch<input value={value.cover_branch||"main"} onChange={e=>setValue({...value,cover_branch:e.target.value})}/></label>
      <label>Cover-letter entry<input value={value.cover_entry||"cover-letter.tex"} onChange={e=>setValue({...value,cover_entry:e.target.value})}/></label></div>
      <h2>Referrals</h2>
      <div className="fields">
        <label>Preferred school and aliases<input maxLength={120} value={value.referral_school ?? ""}
          onChange={e => setValue({...value, referral_school: e.target.value})} placeholder="University of British Columbia, UBC" /></label>
        <label>Preferred experience<input maxLength={240} value={value.referral_experience ?? ""}
          onChange={e => setValue({...value, referral_experience: e.target.value})} placeholder="Prototype testing, hiring, team leadership" /></label>
        <label>Prioritize<select value={value.referral_priority ?? "team"}
          onChange={e => setValue({...value, referral_priority: e.target.value as Profile["referral_priority"]})}>
          <option value="team">Team or role matches</option><option value="school">Preferred school matches</option>
          <option value="experience">Preferred experience matches</option>
        </select></label>
      </div>
      </>}<div className="actions settings-actions">
        {tab==="Discovery" && <button type="button" onClick={() => setValue({...value, searches: [...value.searches, {...blank}]})}>Add saved search</button>}
        <button className="primary" disabled={busy}>Save settings</button>
      </div><p role="status">{message}</p>
    </form>}
  </section>;
}

export function Templates({settings}:{settings:()=>void}){
 const [docs,setDocs]=useState<Document[]>([]),[kind,setKind]=useState("resume"),[selected,setSelected]=useState(""),[message,setMessage]=useState(""),[busy,setBusy]=useState(false);
 const load=async(id="")=>{setDocs(await api<Document[]>("/api/owner/templates"));setSelected(id);};
 useEffect(()=>{load().catch(e=>setMessage(String(e)));},[]);
 const versions=docs.filter(d=>d.kind===kind),doc=versions.find(d=>d.id===selected)||versions[0];
 return <section><div className="document-toolbar"><div className="segmented" role="group" aria-label="Document type">{["resume","cover"].map(k=><button key={k} aria-pressed={kind===k} onClick={()=>{setKind(k);setSelected("");setMessage("")}}>{k==="resume"?"Résumé":"Cover letter"}</button>)}</div>
 <div className="actions"><button className="primary" disabled={busy} onClick={async()=>{setBusy(true);try{const d=await api<{id:string}>("/api/owner/templates/"+kind,"POST");await load(d.id);setMessage("Template imported.");}catch(e){setMessage(String(e))}finally{setBusy(false)}}}>{busy?"Importing…":"Import from GitHub"}</button>
 <button onClick={settings}>Template settings</button></div></div>
 {message&&<p role="status">{message}</p>}{doc?<><label>Version<select value={doc.id} onChange={e=>setSelected(e.target.value)}>{versions.map(d=><option key={d.id} value={d.id}>{new Date(d.created_at).toLocaleString()} · {d.id.slice(0,7)}</option>)}</select></label>
 <Suspense fallback={<p>Opening editor…</p>}><ProjectEditor key={doc.id} doc={doc} tasks={[]} onVersion={load}/></Suspense></>:<p>Import your GitHub project to edit the base template. Tracked roles can use a separate copy.</p>}</section>;
}
