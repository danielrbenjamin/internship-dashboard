import {useEffect,useState} from "react";
import {api} from "./api";
type Mail={accounts:{provider:string;address:string}[];legacy:boolean;sync?:{status:string;checked:string}};
export function MailSettings(){
  const [data,setData]=useState<Mail>(),[provider,setProvider]=useState("Gmail"),[message,setMessage]=useState(""),[busy,setBusy]=useState(false);
  const [device,setDevice]=useState<{code:string;url:string;interval:number}>();
  const load=()=>api<Mail>("/api/owner/mail").then(setData);
  useEffect(()=>{load().catch(e=>setMessage(e.message));},[]);
  useEffect(()=>{
    if(!device)return;
    let stopped=false;let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{try{
      const r=await api<{pending?:boolean}>("/api/owner/mail/microsoft/finish","POST");if(stopped)return;
      if(r.pending){timer=setTimeout(poll,Math.max(5,device.interval)*1000);return;}
      setDevice(undefined);await load();setMessage("Outlook connected.");
    }catch(e){if(!stopped){setDevice(undefined);setMessage(String(e));}}};
    timer=setTimeout(poll,Math.max(5,device.interval)*1000);return ()=>{stopped=true;clearTimeout(timer);};
  },[device]);
  async function run(fn:()=>Promise<void>){setBusy(true);setMessage("");try{await fn();await load();}catch(e){setMessage(String(e));}finally{setBusy(false)}}
  return <section className="desk-card"><h2>Email inboxes</h2>
    {data?.accounts.map(a=><div className="contact-row" key={a.provider}><div><strong>{a.provider}</strong><p>{a.address}</p></div>
      <button disabled={busy} onClick={()=>run(async()=>{await api("/api/owner/mail/"+a.provider,"DELETE");})}>Disconnect</button></div>)}
    {data?.legacy&&<p>Custom IMAP folder connected through server settings.</p>}
    <p>Connect an inbox to find recent employer replies and assessment deadlines.</p>
    <div className="segmented">{["Gmail","Outlook"].map(p=><button key={p} aria-pressed={provider===p} onClick={()=>setProvider(p)}>{p}</button>)}</div>
    {provider==="Gmail"?<form onSubmit={e=>{e.preventDefault();const f=e.currentTarget;const value=Object.fromEntries(new FormData(f));run(async()=>{await api("/api/owner/mail/gmail","POST",value);f.reset();setMessage("Gmail connected.");});}}>
      <label>Gmail address<input name="email" type="email" autoComplete="email" required/></label>
      <label>Google app password<input name="password" type="password" required autoComplete="off"/></label>
      <p><a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">Create an app password in Google</a> after enabling 2-Step Verification.</p>
      <button disabled={busy} className="primary">Connect Gmail</button></form>:<form onSubmit={e=>{e.preventDefault();const value=Object.fromEntries(new FormData(e.currentTarget));run(async()=>setDevice(await api("/api/owner/mail/microsoft","POST",value)));}}>
      <details><summary>Microsoft app setup</summary><ol><li>Open App registrations in Microsoft Entra and register an app for organizational and personal Microsoft accounts.</li><li>Under Authentication, enable public client flows.</li><li>Add delegated Microsoft Graph permissions Mail.Read and User.Read. Copy the Application (client) ID from Overview.</li></ol></details>
      <label>Microsoft application ID<input required name="client_id"/></label><button disabled={busy||!!device}>Connect Outlook</button>
      {device&&<p>Open <a href={device.url} target="_blank" rel="noreferrer">Microsoft sign-in</a> and enter <strong>{device.code}</strong>.</p>}</form>}
    {(data?.legacy||!!data?.accounts.length)&&<div className="actions"><button disabled={busy} onClick={()=>run(async()=>{const r=await api<{status:string}>("/api/owner/mail/check","POST");setMessage(r.status)})}>Check mail now</button>
    {data?.sync&&<small>{data.sync.status} · {new Date(data.sync.checked).toLocaleString()}</small>}</div>}
    <p role="status">{busy?"Checking connection…":message}</p></section>;
}
