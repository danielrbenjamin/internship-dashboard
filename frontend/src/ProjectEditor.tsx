/// <reference types="vite/client" />
import {useEffect, useLayoutEffect, useRef, useState, type CSSProperties} from "react";
import {FolderTree, Maximize2, Minimize2, PanelRight} from "lucide-react";
import {AIBadge, CodexHint} from "./CodexConnection";
import {PaneDivider} from "./PaneDivider";
import * as monaco from "monaco-editor/esm/vs/editor/editor.api";
import "monaco-editor/esm/vs/editor/editor.all";
import Worker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import {useTheme} from "./Theme";
import {api, assetHref, type Task,type Document} from "./api";
import {demoMode} from "./Routes";

self.MonacoEnvironment={getWorker:()=>new Worker()};
monaco.languages.register({id:"latex"});
monaco.languages.setMonarchTokensProvider("latex",{tokenizer:{root:[[/%.*/,"comment"],[/\\[a-zA-Z@]+/,"keyword"],[/[{}]/,"delimiter.bracket"],[/\$.+?\$/,"string"]]}});
type Entry={path:string;editable:boolean};
type Checks={pages:number|null;overfull:number};
type Source={name:string;content:string;tree:Entry[];ancestors?:string[];checks?:Checks|null;parent?:string|null};
type Proposal={key:string;before:string;after:string};
function Files({entries,prefix="",select,active}:{entries:Entry[];prefix?:string;select:(p:string)=>void;active:string}){
  const dirs=new Set(entries.filter(e=>e.path.startsWith(prefix)).map(e=>e.path.slice(prefix.length).split("/")).filter(p=>p.length>1).map(p=>p[0]));
  return <>{[...dirs].sort().map(dir=><details key={dir} open><summary>{dir}</summary><div className="subtree"><Files entries={entries} prefix={prefix+dir+"/"} select={select} active={active}/></div></details>)}
    {entries.filter(e=>e.path.startsWith(prefix)&&!e.path.slice(prefix.length).includes("/")).map(e=><button key={e.path} type="button" disabled={!e.editable} title={e.path} aria-current={active===e.path?"page":undefined} onClick={()=>select(e.path)}>{e.path.slice(prefix.length)}</button>)}</>;
}

function Code({text,proposed,onChange}:{text:string;proposed?:string;onChange:(v:string)=>void}){
  const {dark} = useTheme();
  useEffect(() => {monaco.editor.setTheme(dark ? "vs-dark" : "vs");}, [dark]);
  const host=useRef<HTMLDivElement>(null);
  const cb=useRef(onChange);cb.current=onChange;
  const model=useRef<monaco.editor.ITextModel|null>(null);
  useEffect(()=>{
    if(!host.current)return;
    const original=monaco.editor.createModel(text,"latex");model.current=original;
    const options={automaticLayout:true,minimap:{enabled:false},fontSize:13,scrollBeyondLastLine:false,wordWrap:"on" as const,ariaLabel:"LaTeX source"};
    if(proposed!==undefined){
      const modified=monaco.editor.createModel(proposed,"latex");
      const editor=monaco.editor.createDiffEditor(host.current,{...options,readOnly:true,renderSideBySide:true,originalEditable:false});
      editor.setModel({original,modified});
      let index=0;while(index<text.length && text[index]===proposed[index])index++;
      const line=original.getPositionAt(index).lineNumber;
      editor.getModifiedEditor().revealLineInCenter(line);
      return ()=>{editor.dispose();modified.dispose();original.dispose();model.current=null;};
    }
    const editor=monaco.editor.create(host.current,{...options,model:original});
    const subscription=editor.onDidChangeModelContent(()=>cb.current(original.getValue()));
    return ()=>{subscription.dispose();editor.dispose();original.dispose();model.current=null;};
  },[proposed]);
  useEffect(()=>{if(model.current&&model.current.getValue()!==text)model.current.setValue(text);},[text]);
  return <div className="codepane" ref={host}/>;
}

const defaultLayout = {files: true, pdf: true, filesWidth: 180, pdfWidth: 440};
const editorLayoutKey = "tern.editor-layout";
const demoDrafts = new Map<string, string>();
const draftStorage = {
  getItem: (key: string) => demoMode ? demoDrafts.get(key) ?? null : sessionStorage.getItem(key),
  setItem: (key: string, value: string) => {
    if (demoMode) demoDrafts.set(key, value);
    else sessionStorage.setItem(key, value);
  },
  removeItem: (key: string) => {
    if (demoMode) demoDrafts.delete(key);
    else sessionStorage.removeItem(key);
  },
};

function readLayout(): typeof defaultLayout {
  try {return {...defaultLayout, ...JSON.parse(localStorage.getItem(editorLayoutKey) ?? "{}")};}
  catch {return defaultLayout;}
}

export default function ProjectEditor({doc,tasks,onVersion,suggest,codexReady=false,connectCodex}:{codexReady?:boolean;connectCodex?:()=>void;doc:Document;tasks:Task[];onVersion:(id:string)=>Promise<void>;suggest?:(file:string)=>Promise<void>}){
  const [layout, setLayout] = useState(readLayout);
  const [expanded, setExpanded] = useState(false);
  const studio = useRef<HTMLElement>(null);
  const beforeExpandScroll = useRef(0);
  const expandButton = useRef<HTMLButtonElement>(null);
  const panes = useRef<HTMLDivElement>(null);
  const [paneWidth, setPaneWidth] = useState(0);

  useLayoutEffect(() => {
    if (!panes.current) return;
    const observer = new ResizeObserver(([entry]) => setPaneWidth(entry.contentRect.width));
    observer.observe(panes.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!demoMode) {
      try {localStorage.setItem(editorLayoutKey, JSON.stringify(layout));} catch {}
    }
  }, [layout]);

  function setFocusMode(next: boolean) {
    setExpanded(next);
    expandButton.current?.focus({preventScroll: true});
  }

  useLayoutEffect(() => {
    const workspace = studio.current?.closest("main");
    if (!expanded || !workspace) return;
    beforeExpandScroll.current = workspace.scrollTop;
    workspace.scrollTop = 0;
    const exit = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || document.querySelector("dialog:modal")) return;
      event.preventDefault();
      setFocusMode(false);
    };
    window.addEventListener("keydown", exit, true);
    return () => {
      window.removeEventListener("keydown", exit, true);
      workspace.scrollTop = beforeExpandScroll.current;
    };
  }, [expanded]);

  const minFiles = 128;
  const minPdf = 210;
  const maxFiles = Math.max(minFiles, Math.floor(paneWidth * .34));
  const filesWidth = Math.min(layout.filesWidth, maxFiles);
  const maxPdf = Math.max(minPdf, paneWidth - (layout.files ? filesWidth + 6 : 0) - 240 - 6);
  const pdfWidth = Math.min(layout.pdfWidth, maxPdf);
  const paneStyle = {"--files-width": filesWidth + "px", "--pdf-width": pdfWidth + "px"} as CSSProperties;
  const storageKey="desk.project."+doc.id;
  const [draft,setDraft]=useState<Record<string,string>>(()=>{try{return JSON.parse(draftStorage.getItem(storageKey)||"{}")}catch{return {}}});
  const [created,setCreated]=useState<string[]>(()=>{try{return JSON.parse(draftStorage.getItem(storageKey+".new")||"[]")}catch{return []}});
  const [adding,setAdding]=useState(false);
  const [name,setName]=useState(draftStorage.getItem(storageKey+".file")||doc.entry||"");
  const [source,setSource]=useState<Source>();
  const [tree,setTree]=useState<Entry[]>([]);
  const [compare,setCompare]=useState(false);
  const [previousSource,setPreviousSource]=useState<Source>();
  const [review,setReview]=useState<Proposal>();
  const [ignored,setIgnored]=useState<string[]>(()=>{try{return JSON.parse(draftStorage.getItem(storageKey+".skipped")||"[]")}catch{return []}});
  const [busy,setBusy]=useState(false),[message,setMessage]=useState("");
  const [latestChecks,setChecks]=useState<Checks|null>();
  const checks=latestChecks??source?.checks;
  const [compiled,setCompiled]=useState(!!doc.compiled);
  const path="/api/owner/documents/"+doc.id;
  const text=draft[name]??source?.content??"";
  const proposals:Proposal[]=tasks.flatMap(t=>{
    if(t.status!=="done")return [];
    try{const r=JSON.parse(t.result);if(r.prepared_version||(r.document_id!==doc.id&&!source?.ancestors?.includes(r.document_id))||(r.source_file||doc.entry)!==name)return [];
      return (r.edits||[]).map((e:Proposal,i:number)=>({...e,key:t.id+"-"+i}));}catch{return [];}
  }).filter(p=>!ignored.includes(p.key));
  useEffect(()=>{
    const controller=new AbortController();setSource(undefined);setReview(undefined);setCompare(false);setPreviousSource(undefined);
    if(created.includes(name)){setSource({name,content:"",tree:[]});return;}
    api<Source>(path+"/source?name="+encodeURIComponent(name),"GET",undefined,controller.signal).then(s=>{if(!controller.signal.aborted){setSource(s);setTree(s.tree)}}).catch(e=>{if(!controller.signal.aborted)setMessage(e.message)});
    return ()=>controller.abort();
  },[name,path,created]);
  useEffect(()=>{try{draftStorage.setItem(storageKey,JSON.stringify(draft));draftStorage.setItem(storageKey+".new",JSON.stringify(created))}catch{setMessage("Browser draft storage is full. Save a version before leaving.");}},[storageKey,draft,created]);
  const dirty=Object.keys(draft).length>0;
  const showingPreparedDiff = previousSource?.name === name;
  async function comparePrepared() {
    if (showingPreparedDiff) {
      setPreviousSource(undefined);
      return;
    }
    if (!source?.parent) return;
    try {
      const original = await api<Source>("/api/owner/documents/" + source.parent + "/source?name=" + encodeURIComponent(name));
      setCompare(false);
      setReview(undefined);
      setPreviousSource(original);
    } catch (error) {
      setMessage((error as Error).message);
    }
  }
  function change(v:string){setDraft(prev=>{const d={...prev};if(v===source?.content && !created.includes(name))delete d[name];else d[name]=v;return d;});}
  function dismiss(p:Proposal){const next=[...ignored,p.key];setIgnored(next);draftStorage.setItem(storageKey+".skipped",JSON.stringify(next));setReview(undefined);}
  async function save(compile:boolean){
    setBusy(true);setMessage("");
    let id=doc.id;
    try{
      if(dirty){id=(await api<{id:string}>(path+"/save","POST",{files:draft,created})).id;}
      try{if(compile){const result=await api<{checks:Checks|null}>("/api/owner/documents/"+id+"/compile","POST");setChecks(result.checks);setCompiled(true);}}
      finally{if(id!==doc.id){draftStorage.setItem("desk.project."+id+".file",name);draftStorage.setItem("desk.project."+id+".skipped",JSON.stringify(ignored));if(expanded)draftStorage.setItem("desk.project."+id+".expanded","1");await onVersion(id);draftStorage.removeItem(storageKey);draftStorage.removeItem(storageKey+".new");}}
      setMessage(compile?"PDF compiled.":"Version saved.");
    }catch(e){setMessage(String(e));if(id!==doc.id&&compile)window.alert("Source saved. PDF compilation failed: "+String(e));}finally{setBusy(false);}
  }
  useLayoutEffect(() => {
    const resumeFocus = draftStorage.getItem(storageKey + ".expanded");
    if (resumeFocus) {
      draftStorage.removeItem(storageKey + ".expanded");
      setFocusMode(true);
    }
  }, [storageKey]);

  const proposed=review&&text.includes(review.before)&&text.indexOf(review.before)===text.lastIndexOf(review.before)?text.replace(review.before,()=>review.after):undefined;
  return <section className={expanded ? "studio studio-expanded" : "studio"} ref={studio} aria-label="LaTeX project editor">
    <div className="studio-toolbar">
      <strong>{doc.kind === "cover" ? "Cover letter" : "Résumé"}</strong><span>{dirty ? "Unsaved changes" : "Saved version"}</span>
      <div className="studio-actions">
        <button aria-pressed={layout.files} title={layout.files ? "Hide file tree" : "Show file tree"} onClick={() => setLayout(previous => ({...previous, files: !previous.files}))}>
          <FolderTree size={16} aria-hidden="true" />Files</button>
        <button aria-pressed={layout.pdf} title={layout.pdf ? "Hide PDF preview" : "Show PDF preview"} onClick={() => setLayout(previous => ({...previous, pdf: !previous.pdf}))}>
          <PanelRight size={16} aria-hidden="true" />Preview</button>
        <button ref={expandButton} onClick={() => setFocusMode(!expanded)}>
          {expanded ? <Minimize2 size={16} aria-hidden="true" /> : <Maximize2 size={16} aria-hidden="true" />}
          {expanded ? "Exit full page" : "Full page"}</button>
        <button disabled={busy || !dirty} onClick={() => save(false)}>Save version</button>
        <button className="primary" disabled={busy} onClick={() => save(true)}>Recompile PDF</button>
      </div>
    </div>
    <div className="studio-grid" ref={panes} style={paneStyle}>
    {layout.files && <><aside className="filetree"><h3>Files</h3><button disabled={busy} onClick={()=>setAdding(!adding)}>+ New file</button>
    {adding&&<form onSubmit={e=>{e.preventDefault();const n=String(new FormData(e.currentTarget).get("path")||"").trim();
      if(!n||!n.split("/").every(p=>/^[\w +-][\w .+-]*$/.test(p)&&!p.endsWith("."))||!/[.](tex|sty|cls|bib|txt|md|bst|cfg|def)$/i.test(n)||[...tree.map(f=>f.path),...created].some(p=>p.toLowerCase()===n.toLowerCase())){setMessage("Choose a new relative source filename, such as sections/projects.tex.");return}
      setCreated([...created,n]);setDraft({...draft,[n]:""});setName(n);setAdding(false);
    }}><label>File path<input name="path" required autoFocus/></label><button>Create</button></form>}
    <Files entries={[...tree,...created.map(path=>({path,editable:true}))]} active={name} select={setName}/></aside>
    <PaneDivider label="Resize file tree" min={minFiles} max={maxFiles} value={filesWidth} direction={1}
      onResize={width => setLayout(previous => ({...previous, filesWidth: width}))} /></>}
    <section className="editor-pane"><div className="pane-title">{name} {showingPreparedDiff ? " · Previous ↔ Prepared PDF source" : review?" · Current ↔ Codex proposal":compare?" · Saved ↔ Working copy":""}</div>
    {source ? <Code key={name} text={showingPreparedDiff ? previousSource.content : compare?source.content:text}
      proposed={showingPreparedDiff ? source.content : compare?text:proposed} onChange={change}/> : <p>Loading file…</p>}
    <div className="editor-review">{source&&draft[name]!==undefined&&!review&&<button onClick={()=>setCompare(!compare)}>{compare?"Back to editor":"Compare working copy"}</button>}{suggest&&<button disabled={!codexReady||dirty||busy||!name.endsWith(".tex")||!source||tasks.some(t=>["queued","running"].includes(t.status))} onClick={async()=>{setBusy(true);try{await suggest(name)}catch(e){setMessage(String(e))}finally{setBusy(false)}}}>Request Codex edits <AIBadge /></button>}
    {doc.verified && name === doc.entry && source?.parent && <button onClick={() => void comparePrepared()}>
      {showingPreparedDiff ? "Back to editor" : "Compare prepared version"}</button>}
    {suggest && !codexReady && connectCodex && <CodexHint connect={connectCodex} />}
    {dirty&&suggest&&<small> Save this version before requesting more edits.</small>}
    {!showingPreparedDiff && proposals.map((p,i)=><div className="actions" key={p.key}><button onClick={()=>{setCompare(false);setReview(p)}}>Review change {i+1}</button> <button onClick={()=>dismiss(p)}>Skip</button></div>)}
    {review&&<div className="actions">{proposed!==undefined?<button className="primary" onClick={()=>{change(proposed);dismiss(review)}}>Merge this change</button>:<p>The original text changed or appears more than once. Review the suggestion manually.</p>}
    <button onClick={()=>setReview(undefined)}>Back to editor</button></div>}</div></section>
    {layout.pdf && <><PaneDivider label="Resize PDF preview" min={minPdf} max={maxPdf} value={pdfWidth} direction={-1}
      onResize={width => setLayout(previous => ({...previous, pdfWidth: width}))} />
    <aside className="preview-pane"><div className="pane-title">PDF preview {dirty&&"· last compiled version"}</div>
    {checks&&<p role="status">{checks.pages!=null&&` ${checks.pages} ${checks.pages===1?"page":"pages"}. `}{checks.overfull>0&&` ${checks.overfull} layout overflow warning${checks.overfull===1?"":"s"}.`}{!!checks.pages&&checks.pages>1&&doc.kind!=="cover"&&" Review the résumé length before submitting."}</p>}{compiled?<iframe title="Compiled document" src={assetHref(path+"/pdf")}/>:<p>Recompile to preview this version.</p>}</aside></>}</div>
    {message&&<p className="studio-message" role="status">{message}</p>}</section>;
}
