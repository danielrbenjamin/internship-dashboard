import {Bell, BookOpen, Building2, CalendarDays, ChartNoAxesCombined, ChevronDown, Files, House, Inbox, ListFilter, LogOut, Play, Send, Settings, Star, Users, Search, Moon, Sun, PanelLeftClose} from "lucide-react";
import {useEffect, useRef, useState} from "react";
import {useTheme} from "./Theme";
import {demoMode, publicViews} from "./Routes";
import {BrandMark} from "./Brand";
export type View = "Background" | "Needs" | "Screening" | "Replies" | "Referrals" | "Materials" | "Overview" | "Browse" | "Saved" | "Applied" | "Alerts" | "Sources" | "Settings" | "Analytics" | "Interviews";
const sections=[
  {name:"Workspace",links:[["Overview","Overview",House],["Needs","Needs you",Inbox],["Analytics","Analytics",ChartNoAxesCombined],["Background","Background work",ListFilter],["Alerts","Alerts",Bell]]},
  {name:"Jobs",links:[["Browse","All openings",BookOpen],["Screening","Where to apply",ListFilter],["Saved","Saved roles",Star],["Materials","Application materials",Files],["Applied","Applied",Send],["Interviews","Interviews",CalendarDays]]},
  {name:"Inbox & network",links:[["Replies","Email & deadlines",Inbox],["Referrals","Referrals",Users]]},
  {name:"Setup",links:[["Sources","Sources",Building2],["Settings","Settings",Settings]]}
] as const;
export function Navigation({view,navigate,owner,account,loginAvailable,signInHelp,onSignIn,onSignOut,unread,openSettings,collapsed,toggleSidebar,signInUrl}:{
  signInUrl:string;collapsed:boolean;toggleSidebar:()=>void;
  view:View;navigate:(view:View)=>void;owner:boolean;account?:{name?:string;email?:string;picture?:string};loginAvailable:boolean;
  signInHelp:boolean;onSignIn:()=>void;onSignOut:()=>void;unread:number;openSettings:(tab:string)=>void;
}){
  const {dark, toggleDark} = useTheme();
  const name=account?.name||account?.email||"Google account";
  const brand = useRef<HTMLButtonElement>(null);
  const accountButton = useRef<HTMLButtonElement>(null);
  const accountMenu = useRef<HTMLDivElement>(null);
  const dialog=useRef<HTMLDialogElement>(null);
  const [query,setQuery]=useState("");
  const [accountOpen, setAccountOpen] = useState(false);
  useEffect(() => {
    const dismiss = () => {
      if (accountMenu.current?.matches(":popover-open")) accountMenu.current.hidePopover();
    };
    window.addEventListener("resize", dismiss);
    window.addEventListener("scroll", dismiss, true);
    return () => {
      window.removeEventListener("resize", dismiss);
      window.removeEventListener("scroll", dismiss, true);
    };
  }, []);
  useEffect(() => {
    if (accountMenu.current?.matches(":popover-open")) accountMenu.current.hidePopover();
  }, [view, collapsed]);
  function showSearch(){
    setQuery("");
    if(!dialog.current?.open)dialog.current?.showModal();
  }
  useEffect(()=>{
    const shortcut=(event:KeyboardEvent)=>{
      if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="k"){
        event.preventDefault();
        showSearch();
      }
    };
    window.addEventListener("keydown",shortcut);
    return ()=>window.removeEventListener("keydown",shortcut);
  },[]);
  const pages=sections.flatMap(section=>section.links.map(([target,label])=>({target,label})))
    .filter(({target})=>owner||publicViews.includes(target))
    .map(({target,label})=>({label,open:()=>navigate(target)}));
  const settings=["Profile","Discovery","Email inboxes","Codex"];
  const commands=[...pages,...(owner ? settings.map(tab=>({label:"Settings · "+tab,open:()=>openSettings(tab)})) : [])]
    .filter(command=>command.label.toLowerCase().includes(query.trim().toLowerCase()));
  function select(command:typeof commands[number]){
    dialog.current?.close();
    command.open();
  }
  return <aside className="navigation">
    <div className="nav-heading">
      <button ref={brand} className="brand" aria-label={collapsed ? "Expand sidebar" : "Tern"}
        title={collapsed ? "Expand sidebar" : undefined}
        aria-expanded={collapsed ? false : undefined} aria-controls={collapsed ? "sidebar-views" : undefined}
        onClick={collapsed ? toggleSidebar : () => navigate("Overview")}><BrandMark /><span>Tern</span></button>
      {!collapsed && <button className="sidebar-toggle" onClick={() => { toggleSidebar(); brand.current?.focus(); }} aria-expanded
        aria-controls="sidebar-views" aria-label="Collapse sidebar" title="Collapse sidebar">
        <PanelLeftClose size={17} />
      </button>}
    </div>
    <button className="app-search-trigger" aria-label="Search the app" title="Search the app" onClick={showSearch}><Search size={15}/> <span>Search the app</span> <kbd>Ctrl K</kbd></button>
    <dialog className="app-search" ref={dialog} aria-label="Search the app" onClick={event => {
      if (event.target !== event.currentTarget) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right ||
          event.clientY < bounds.top || event.clientY > bounds.bottom) event.currentTarget.close();
    }}>
      <form onSubmit={event=>{event.preventDefault();if(commands[0])select(commands[0]);}}>
        <label>Find a page or setting<input value={query} onChange={event=>setQuery(event.target.value)} autoFocus /></label>
      </form>
      <div className="app-search-results">{commands.map(command=><button key={command.label} onClick={()=>select(command)}>{command.label}</button>)}
      {!commands.length && <p>No matching pages.</p>}</div>
    </dialog>
    <nav id="sidebar-views" aria-label="Dashboard views">{sections.map(s=>{
      const links=s.links.filter(([v])=>owner||publicViews.includes(v));
      return links.length>0&&<div className="nav-group" key={s.name}><h2>{s.name}</h2>{links.map(([v,title,Icon])=><button key={v} aria-label={title} title={title} aria-current={v===view?"page":undefined} onClick={()=>navigate(v)}>
        <Icon size={16} strokeWidth={1.7}/><span className="nav-label">{title}</span>{v==="Alerts"&&unread>0&&<span className="unread">{unread}</span>}</button>)}</div>})}</nav>
    <div className="sidebar-footer">
      <button className="theme-control" aria-label={dark ? "Light mode" : "Dark mode"} title={dark ? "Light mode" : "Dark mode"} onClick={toggleDark}>
        {dark ? <Sun size={15} aria-hidden="true" /> : <Moon size={15} aria-hidden="true" />}
        <span>{dark ? "Light mode" : "Dark mode"}</span>
      </button>
      <div className="account-control">{owner ? <>
        <button className="account-trigger" ref={accountButton} popoverTarget="account-menu" aria-controls="account-menu"
          aria-expanded={accountOpen} aria-label={name} title={name}>
          {account?.picture ? <img className="avatar" referrerPolicy="no-referrer" src={account.picture} alt="" /> :
            <span className="avatar">{name.slice(0,1).toUpperCase()}</span>}
          <span className="account-name">{name}{demoMode && " · Demo"}</span><ChevronDown size={14} aria-hidden="true" />
        </button>
        <div id="account-menu" className="account-menu" popover="auto" ref={accountMenu}
          onBeforeToggle={event => {
            if (event.newState !== "open" || !accountButton.current) return;
            const bounds = accountButton.current.getBoundingClientRect();
            const width = Math.min(240, window.innerWidth - 16);
            const left = collapsed && window.innerWidth > 780 ? bounds.right + 8 : bounds.left;
            const menu = event.currentTarget;
            menu.style.left = Math.max(8, Math.min(left, window.innerWidth - width - 8)) + "px";
            menu.style.bottom = bounds.top > 150 ? window.innerHeight - bounds.top + 6 + "px" : "auto";
            menu.style.top = bounds.top > 150 ? "auto" : bounds.bottom + 6 + "px";
          }} onToggle={event => setAccountOpen(event.newState === "open")}>
          {account?.email && <small>{account.email}</small>}
          <button onClick={() => {accountMenu.current?.hidePopover(); onSignOut();}}><LogOut size={15}/>{demoMode ? "Exit demo" : "Sign out"}</button>
        </div>
      </> : <>
        <a className="button demo-link" href="/demo" aria-label="Demo mode" title="Demo mode"><Play size={15} /><span>Demo mode</span></a>
        {loginAvailable ? <a className="button" aria-label="Sign in with Google" title="Sign in with Google" href={signInUrl}><span className="google-mark">G</span><span>Sign in with Google</span></a> :
          <button aria-expanded={signInHelp} aria-label="Sign in with Google" title="Sign in with Google" onClick={onSignIn}><span className="google-mark">G</span><span>Sign in with Google</span></button>}
      </>}</div></div></aside>;
}

