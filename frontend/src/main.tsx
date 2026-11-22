
import {lazy, Suspense, useCallback, useEffect, useRef, useState} from "react";
import {BriefcaseBusiness, List, Map as MapIcon, Maximize2, Minimize2, Search as SearchIcon, SlidersHorizontal} from "lucide-react";
import {createRoot} from "react-dom/client";
import {api, ApiError, formatDate, statuses} from "./api";
import type {Alert, Application, CatalogSource, Job, Profile} from "./api";
import {PostingText} from "./PostingText";
import {Overview} from "./Overview";
import {Analytics} from "./Analytics";
import {Demo} from "./Demo";
import {Interviews} from "./Interviews";

import {Navigation} from "./Navigation";
import type {View} from "./Navigation";
import {publicViews, readRoute, routeUrl, type Route} from "./Routes";
import {Referrals} from "./Referrals";
import {useCodexStatus} from "./CodexConnection";
import {useDeadlineNotifications} from "./DeadlineNotifications";
import {SearchableSelect} from "./SearchableSelect";
import {ThemeProvider} from "./Theme";
import {BrandIntro} from "./Brand";
import {PageHeader} from "./PageHeader";
import {Background, NeedsYou} from "./Background";
import {Screening, Replies} from "./Workflows";
import {SettingsPanel, Templates, Workspace} from "./Workspace";
import "@fontsource-variable/space-grotesk";
import "@fontsource-variable/jetbrains-mono";
import "./styles.css";

const LocationMap = lazy(() => import("./LocationMap"));
const sourceNames: Record<string, string> = {amd: "AMD", apple: "Apple", disney: "Disney",
  google: "Google", neuralink: "Neuralink", tesla: "Tesla", zipline: "Zipline", amazon: "Amazon",
  "boards:simplify": "SimplifyJobs"};
const sourceName = (id: string) => sourceNames[id] || id;
const sourceLinks: Record<string, string> = {
  google: "https://www.google.com/about/careers/applications/jobs/results/?q=intern",
  apple: "https://jobs.apple.com/en-us/search?team=internships-STDNT-INTRN",
  amd: "https://careers.amd.com/careers-home/jobs",
  disney: "https://www.disneycareers.com/en/imagineering-jobs",
  "boards:simplify": "https://github.com/SimplifyJobs/Summer2027-Internships",
  zipline: "https://www.zipline.com/open-roles", neuralink: "https://neuralink.com/careers/",
  amazon: "https://www.amazon.jobs/en/search?base_query=internship",
};
const postSubmission = (item: Application) => ["applied", "interview", "offer", "closed"].includes(item.status);

function postingAge(postedOn: string) {
  const today = new Date();
  const calendarDay = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  const days = Math.max(0, Math.round((calendarDay - Date.parse(postedOn)) / 86400000));
  return days === 0 ? "Today" : days === 1 ? "1 day ago" : days + " days ago";
}

function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem("tern.sidebar-collapsed") === "true");
  useEffect(() => {localStorage.setItem("tern.sidebar-collapsed", String(sidebarCollapsed));}, [sidebarCollapsed]);
  const [session, setSession] = useState<{owner: boolean; login_available: boolean;account?:{name?:string;email?:string;picture?:string}}>();
  const [route, setRoute] = useState(readRoute);
  const {view, job: selected = "", tab: settingsTab = "Profile", company: referralCompany = "",
    team: referralTeam = "", reply: focusItem = ""} = route;
  const [signInNotice, setSignInNotice] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [applications, setApplications] = useState<Application[]>([]);
  const [profile, setProfile] = useState<Profile>();
  const [coverage, setCoverage] = useState<CatalogSource[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [reminders,setReminders] = useState<{id:number;subject:string;due:string}[]>([]);
  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");
  const [discipline, setDiscipline] = useState("");
  const [disciplines, setDisciplines] = useState<string[]>([]);
  const [rule, setRule] = useState("");
  const [term, setTerm] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [catalogFocus, setCatalogFocus] = useState<"list" | "details" | null>(null);
  const [mode, setMode] = useState<"List" | "Map">("List");
  const [detail, setDetail] = useState<Job>();
  const [detailError, setDetailError] = useState("");
  const [total, setTotal] = useState<number>();
  const sentinel = useRef<HTMLDivElement>(null);
  const loadMore = useRef<() => void>(() => {});
  const [retry, setRetry] = useState(false);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const searchInput = useRef<HTMLInputElement>(null);

  const owner = session?.owner;
  const demo = view === "Demo";
  const codexStatus = useCodexStatus(Boolean(owner) && !demo);
  const codexReady = codexStatus === "connected";
  const deadlineNotifications=useDeadlineNotifications(reminders,Boolean(owner) && !demo);
  const refresh = useCallback(async () => {
    try {
      const [apps, options, notifications, due] = await Promise.all([
        api<Application[]>("/api/owner/applications"), api<Profile>("/api/owner/settings"),
        api<Alert[]>("/api/owner/alerts"), api<typeof reminders>("/api/owner/reminders"),
      ]);
      setReminders(due); setApplications(apps); setProfile(options); setAlerts(notifications);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setSession(previous => previous && {...previous, owner: false});
        setRule(""); setReminders([]);
        setApplications([]); setProfile(undefined); setAlerts([]);
      }
      throw error;
    }
  }, []);
  useEffect(() => {
    const restore = () => {
      setRoute(readRoute());
      setCatalogFocus(null);
      setMessage("");
      setStatusFilter("");
    };
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  const showError = (error: Error) => setMessage(error.message);

  useEffect(() => {
    const controller = new AbortController();
    api<NonNullable<typeof session>>("/api/session", "GET", undefined, controller.signal)
      .then(setSession).catch(error => {if (!controller.signal.aborted) showError(error);});
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (demo) return;
    const controller = new AbortController();
    const update = () => void api<CatalogSource[]>("/api/sources", "GET", undefined, controller.signal)
      .then(setCoverage).catch(() => {});
    update();
    const timer = window.setInterval(update, 60000);
    return () => {controller.abort(); window.clearInterval(timer);};
  }, [demo]);
  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.key === "/" && !target?.closest("input, textarea, select, [contenteditable]") && searchInput.current) {
        event.preventDefault(); searchInput.current.focus();
      }
      if (event.key === "Escape" && ["Browse", "Saved", "Applied"].includes(view) &&
          !target?.closest("input, textarea, select, [contenteditable], dialog") &&
          !document.querySelector(".account-menu:popover-open")) {
        if (catalogFocus) setCatalogFocus(null);
        else closeDetails();
      }
    };
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, [selected, view, catalogFocus, mode]);
  useEffect(() => {
    if (!owner || demo) return;
    void refresh().catch(showError);
    const timer = window.setInterval(() => void refresh().catch(showError), 30000);
    return () => window.clearInterval(timer);
  }, [owner, refresh, demo]);
  useEffect(() => {
    if (view !== "Browse") return;
    const controller = new AbortController();
    let offset = 0;
    let busy = false;
    let hasMore = false;
    setLoading(true); setJobs([]); setTotal(undefined); setMore(false); setRetry(false);
    const load = async (append = false) => {
      if (busy || (append && !hasMore)) return;
      busy = true;
      setLoading(true); setRetry(false);
      try {
        const params = new URLSearchParams({q: query, location, offset: String(append ? offset : 0),
          term, discipline, source: sourceFilter, map_view: String(mode === "Map")});
        if (rule === "watchlist") params.set("watchlist", "true");
        else if (rule) params.set("saved_search", rule);
        const data = await api<{jobs: Job[]; has_more: boolean; disciplines?: string[]; total?: number}>("/api/jobs?" + params, "GET", undefined, controller.signal);
        if (controller.signal.aborted) return;
        if (!Array.isArray(data.disciplines)) throw new Error("Restart the catalog server to load recent postings and discipline filters.");
        offset = (append ? offset : 0) + data.jobs.length;
        hasMore = data.has_more && data.jobs.length > 0;
        setDisciplines(data.disciplines); setMore(hasMore);
        if (!append) setTotal(data.total);
        setJobs(previous => {
          if (!append) return data.jobs;
          const seen = new Set(previous.map(job => job.id));
          return [...previous, ...data.jobs.filter(job => !seen.has(job.id))];
        });
      } catch (error) {
        if (!controller.signal.aborted) {showError(error as Error); setRetry(true);}
      } finally {
        busy = false;
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    loadMore.current = () => void load(offset > 0);
    const timer = window.setTimeout(() => void load(), 180);
    const refreshTimer = window.setInterval(() => {
      if (mode === "Map" || offset <= 100) void load();
    }, 60000);
    return () => {controller.abort(); window.clearTimeout(timer); window.clearInterval(refreshTimer);};
  }, [query, location, rule, term, discipline, sourceFilter, mode, view, profile?.searches.length]);
  useEffect(() => {
    if (!sentinel.current || !more || loading || retry || view !== "Browse" || mode !== "List") return;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) loadMore.current();
    }, {rootMargin: "180px"});
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [more, loading, retry, view, mode, jobs.length]);
  useEffect(() => {
    setDetail(undefined);
    setDetailError("");
    if (!selected || (!publicViews.includes(view) && !owner)) return;
    const controller = new AbortController();
    api<Job>("/api/jobs/" + selected, "GET", undefined, controller.signal)
      .then(value => {if (!controller.signal.aborted) setDetail(value);})
      .catch(error => {if (!controller.signal.aborted) setDetailError(error.message);});
    return () => controller.abort();
  }, [selected, owner, view]);

  const currentApplication = applications.find(item => item.job_id === selected);
  const tracked = applications.filter(item => view === "Applied" ? postSubmission(item) : !postSubmission(item))
    .filter(item => (item.title + " " + item.company).toLowerCase().includes(query.toLowerCase())
      && (item.location || "").toLowerCase().includes(location.toLowerCase())
      && (!statusFilter || statusFilter === item.status));
  const rows = view === "Browse" ? jobs : tracked;
  const unread = alerts.filter(item => !item.read).length;
  const configured = coverage.filter(source => source.status !== "reference");
  const activeSources = configured.filter(source => source.status === "current").length;
  const sourceLabel = (id: string) => coverage.find(source => source.id === id)?.label || sourceName(id);

  function goTo(next: Route) {
    const url = routeUrl(next);
    if (url === window.location.pathname + window.location.search) return;
    window.history.pushState(null, "", url);
    setRoute(next);
    setMessage("");
  }

  function navigate(next: View, options: Omit<Route, "view"> = {}) {
    setCatalogFocus(null);
    goTo({view: next, ...options});
    setStatusFilter("");
    setSignInNotice(false);
  }

  function setSelected(job: string) {
    goTo({...route, job});
  }

  function openPriority(target: "Replies" | "Referrals" | "Materials", id: string, company?: string) {
    if (target === "Materials") navigate(target, {job: id});
    else if (target === "Referrals") navigate(target, {company});
    else navigate(target, {reply: id});
  }

  function closeDetails() {
    if (!selected) return;
    const control = document.querySelector<HTMLButtonElement>(`[data-job="${CSS.escape(selected)}"]`);
    setSelected("");
    if (catalogFocus === "details") {
      setCatalogFocus(mode === "List" ? "list" : null);
      requestAnimationFrame(() => control?.focus({preventScroll: true}));
    } else {
      control?.focus({preventScroll: true});
    }
  }

  const openCodexSettings = () => navigate("Settings", {tab:"Codex"});
  const openSource = (id: string) => {setSourceFilter(id); setFiltersOpen(true); navigate("Browse");};
  const protectedPage = !publicViews.includes(view);
  const signInUrl = "/auth/login?next=" + encodeURIComponent(routeUrl(route));
  const isCatalog = view === "Browse" || view === "Saved" || view === "Applied";
  const expandedPane = isCatalog ? catalogFocus : null;
  function togglePosting(job: string) {
    if (selected === job) {
      closeDetails();
    } else {
      setSelected(job);
      if (expandedPane === "list") setCatalogFocus("details");
    }
  }

  const hasFilters = Boolean(query || location || statusFilter || (view === "Browse" && (term || discipline || sourceFilter || rule)));
  return <>
    <BrandIntro />
    <div className={["layout", sidebarCollapsed && "sidebar-collapsed", expandedPane && "catalog-expanded"].filter(Boolean).join(" ")}>
      <a className="skip" href="#main">Skip to content</a>
      <Navigation collapsed={sidebarCollapsed} toggleSidebar={()=>setSidebarCollapsed(value=>!value)} openSettings={tab=>navigate("Settings",{tab})} signInUrl={signInUrl} view={view} navigate={navigate} account={session?.account} owner={Boolean(owner)} loginAvailable={Boolean(session?.login_available)}
        signInHelp={signInNotice} onSignIn={() => setSignInNotice(!signInNotice)} unread={unread}
        onSignOut={() => {void api<{redirect: string}>("/auth/logout", "POST")
          .then(result => window.location.assign(result.redirect)).catch(showError);}} />
      <main id="main" tabIndex={-1} className={isCatalog ? "panel catalog jobs-page" + (expandedPane ? " catalog-focus-" + expandedPane : "") : view === "Materials" || view === "Screening" ? "panel page jobs-page" : "panel page"}>
        {signInNotice && !owner && !session?.login_available && <section id="sign-in-help" className="notice" aria-label="Owner sign-in setup">
          <strong>Owner sign-in needs Auth0 setup.</strong>
          <p>Set the Auth0 web application details and your owner subject in the local environment, then restart the app.</p>
          <p>Local callback <code>{window.location.origin}/auth/callback</code></p>
        </section>}
        {owner && !demo && !!reminders.length && view!=="Replies" && <p className="notice"><button onClick={()=>navigate("Replies")}>{reminders.length} due or overdue · {reminders[0].subject}</button></p>}
        {!!message && <p className="notice" role="alert">{message} <button onClick={() => setMessage("")}>Dismiss</button></p>}
        {protectedPage && !owner ? <section className="desk-page">
          {session ? <>
            <PageHeader title="Sign in to Tern" />
            {session.login_available ? <a className="button primary" href={signInUrl}>Sign in with Google</a> :
              <p>Owner sign-in is unavailable.</p>}</> : <p role="status">Checking sign-in…</p>}
        </section> : view === "Needs" ? <NeedsYou open={openPriority}/> :
        view === "Demo" ? <Demo exit={() => navigate("Overview")}/> :
        view === "Analytics" ? <Analytics sourceName={sourceLabel} openSource={openSource}/> :
        view === "Interviews" ? <Interviews open={id=>navigate("Materials",{job:id})} openEmail={reply=>navigate("Replies",{reply})}/> :
        view === "Background" ? <Background open={id=>navigate("Materials",{job:id})}/> : view === "Referrals" ? <Referrals apps={applications} initialCompany={referralCompany} initialTeam={referralTeam}/> : view === "Screening" ? <Screening codexReady={codexReady} connectCodex={openCodexSettings} materials={id=>navigate("Materials",{job:id})} settings={()=>navigate("Settings",{tab:"Discovery"})} open={id=>navigate("Browse",{job:id})}/> :
        view === "Replies" ? <Replies notifications={deadlineNotifications} focus={focusItem} apps={applications} connect={()=>navigate("Settings",{tab:"Email inboxes"})}/> : view === "Overview" ? <Overview openPriority={openPriority} name={session?.account?.name} tasks={owner?[{label:"Ready to submit",value:applications.filter(a=>a.status==="ready").length,open:()=>{navigate("Saved");setStatusFilter("ready")}},{label:"Due or overdue",value:reminders.length,open:()=>navigate("Replies")},{label:"New matches",value:unread,open:()=>navigate("Alerts")}]:[]} owner={Boolean(owner)} sourceName={sourceLabel}
          openCatalog={() => navigate("Browse")}
          openSource={openSource} /> :
        view === "Materials" ? <section className="materials-page"><PageHeader title="Application materials" />
          <div className="jobs-toolbar">
            <SearchableSelect label="Application" value={selected} onChange={setSelected} options={[
              {value:"", label:"My templates"},
              ...(selected && !currentApplication && detail ? [{value:selected, label:detail.company+" · "+detail.title}] : []),
              ...applications.map(item => ({value:item.job_id, label:item.company+" · "+item.title})),
            ]} />
          </div>
          {!selected ? <Templates settings={()=>navigate("Settings")}/> : detail?.id === selected && detail ? <Workspace key={selected} codexReady={codexReady} connectCodex={openCodexSettings} job={detail} application={currentApplication} reload={refresh} />
            : <p>{selected ? detailError || "Loading application…" : "Select a tracked application or open a posting from the inbox."}</p>}
        </section> : view === "Sources" ? <Coverage sources={coverage} /> : view === "Settings" ? profile ? <SettingsPanel codexStatus={codexStatus} tab={settingsTab} setTab={tab=>navigate("Settings",{tab})} profile={profile} save={async value => {
          await api("/api/owner/settings", "PUT", value); setRule(""); await refresh();
        }} /> : <p role="status">Loading settings…</p> : view === "Alerts" ? <section className="desk-page">
          <PageHeader title="Alerts">{!!unread && <button onClick={() => api("/api/owner/alerts/read", "POST").then(refresh).catch(showError)}>Mark all read</button>}</PageHeader>
          {alerts.length ? <ul className="sources">{alerts.map(item => <li key={item.job_id}>
            <button onClick={() => navigate("Browse",{job:item.job_id})}>{item.title} · {item.company}</button>
            <span>{!item.read && "New · "}{formatDate(item.created_at)}</span></li>)}</ul>
          : <p className="muted">New matches from your watchlist and saved searches appear here.</p>}
        </section> : <>
          <PageHeader title={view === "Browse" ? "All openings" : view === "Saved" ? "Saved roles" : "Applied"} className="catalog-title">
            {view === "Browse" && configured.length > 0 && <button className="coverage-link" onClick={() => navigate("Sources")}>
              <span className={activeSources < configured.length ? "source-dot warning" : "source-dot"} />
              {activeSources}/{configured.length} sources current</button>}</PageHeader>
          <div className="jobs-toolbar catalog-toolbar">
            <label className="search-field"><SearchIcon size={16} aria-hidden="true" /><span className="sr-only">Search</span>
              <input type="search" ref={searchInput} maxLength={160} placeholder="Search roles or companies" value={query}
                onChange={e => {setQuery(e.target.value);}} /></label>
            <button aria-expanded={filtersOpen} aria-controls="catalog-filters" onClick={() => setFiltersOpen(!filtersOpen)}>
              <SlidersHorizontal size={16} aria-hidden="true" />Filters</button>
            <div className="segmented" role="group" aria-label="Catalog layout">
              {(["List", "Map"] as const).map(value => {
                const Icon = value === "List" ? List : MapIcon;
                return <button key={value} aria-pressed={mode === value} onClick={() => {setMode(value);setCatalogFocus(null);}}>
                  <Icon size={15} aria-hidden="true" />{value}</button>;
              })}
            </div>
            {hasFilters && <button className="clear-filters" onClick={() => {
              setQuery(""); setLocation(""); setTerm(""); setDiscipline(""); setSourceFilter(""); setRule(""); setStatusFilter("");
            }}>Clear filters</button>}
          </div>
          {view !== "Browse" && <div className="pipeline" aria-label="Filter by application status">
            {(view === "Saved" ? statuses.slice(0, 3) : statuses.slice(3)).map(status =>
              <button key={status} aria-pressed={status === statusFilter}
                onClick={() => setStatusFilter(statusFilter === status ? "" : status)}>
                <span>{status}</span><strong>{applications.filter(item => item.status === status).length}</strong></button>)}
          </div>}
          <div className="filters" id="catalog-filters" hidden={!filtersOpen}>
            <label>Location<input type="search" maxLength={100} placeholder="City, region or country" value={location}
              onChange={e => {setLocation(e.target.value);}} /></label>
            {view === "Browse" && <><label>Discipline<select value={discipline} onChange={e => {
              setDiscipline(e.target.value); setSelected("");
            }}>
              <option value="">All disciplines</option>{disciplines.map(value => <option key={value}>{value}</option>)}
            </select></label><label>Term<select value={term} onChange={e => {setTerm(e.target.value);}}>
              <option value="">Any term</option>{["Summer 2027", "Spring 2027", "Fall 2027", "Winter 2027"].map(value =>
                <option key={value}>{value}</option>)}
            </select></label>
            <SearchableSelect label="Source" value={sourceFilter} onChange={setSourceFilter} options={[
              {value:"", label:"All sources"},
              ...configured
                .filter(source => source.kind !== "board_index" && (!source.id.startsWith("ats:") || source.count > 0))
                .map(source => ({value:source.id, label:sourceLabel(source.id), keywords:source.id})),
            ]} /></>}
            {owner && view === "Browse" && <label>Feed<select value={rule} onChange={e => {setRule(e.target.value);}}>
              <option value="">All openings</option><option value="watchlist">Watchlist</option>
              {profile?.searches.map((item, index) => <option key={index} value={index}>{item.name}</option>)}
            </select></label>}
          </div>
          <div className={"inbox" + (selected ? " selected" : "") + (mode === "Map" ? " map-inbox" : "") + (expandedPane ? " single-pane" : "")}>
            {mode === "Map" ? <div className="catalog-map" hidden={expandedPane === "details"}><Suspense fallback={<p role="status">Loading map…</p>}>
              <LocationMap roles={rows.map(row => ({...row, id: "job_id" in row ? row.job_id : row.id}))}
                onRole={togglePosting} capped={view === "Browse" && more} />
            </Suspense></div> : <section hidden={expandedPane === "details"} className={selected && !expandedPane ? "feed" : "feed jobs-table"} aria-label={view === "Browse" ? "Openings" : "Tracked applications"} aria-busy={view === "Browse" && loading}>
              <div className="feed-head"><span role="status">{view === "Browse"
                ? total !== undefined ? `${total.toLocaleString()} ${total === 1 ? "opening" : "openings"}`
                  : loading ? "Loading openings…" : more ? `${rows.length} openings loaded` : `${rows.length} openings`
                : `${rows.length} ${rows.length === 1 ? "application" : "applications"}`}</span>
                <div className="pane-actions">
                  {view !== "Browse" && <span>Status</span>}
                  <button type="button" onClick={() => setCatalogFocus(expandedPane === "list" ? null : "list")}
                    aria-label={expandedPane === "list" ? "Exit full-page openings" : "Expand openings"}
                    title={expandedPane === "list" ? "Exit full page" : "Expand openings"}>
                    {expandedPane === "list" ? <Minimize2 size={15} aria-hidden="true" /> : <Maximize2 size={15} aria-hidden="true" />}
                  </button>
                </div>
              </div>
              {rows.map(row => {
                const tracked = "job_id" in row;
                const id = tracked ? row.job_id : row.id;
                const date = tracked ? undefined : row.posted_on;
                const term = !tracked && row.term && !row.title.toLowerCase().includes(row.term.toLowerCase()) ? row.term : "";
                return <button key={id} data-job={id} className={"job job-list-row" + (selected === id ? " chosen" : "")}
                  aria-pressed={selected === id} onClick={() => togglePosting(id)}>
                  <span className="job-list-icon"><BriefcaseBusiness aria-hidden="true" size={19} strokeWidth={1.6} /></span>
                  <span className="job-list-copy">
                    <span className="job-context">
                      <span className="job-company">{row.company}</span>
                      {date && <time dateTime={date} title={formatDate(date + "T12:00:00")}>{postingAge(date)}</time>}
                      {row.location && <span>{row.location}</span>}
                      {term && <span>{term}</span>}
                    </span>
                    <strong>{row.title}</strong>
                  </span>
                  {tracked && <span className="row-meta job-status">{row.status}</span>}
                </button>;
              })}
              {!rows.length && (view !== "Browse" || !loading) && <div className="empty">
                <strong>{view === "Browse" ? "No openings found" : "No applications here yet"}</strong>
                <p>{hasFilters ? "Try widening your filters." : view === "Browse" ?
                  "No openings with a posting date in the last 30 days." : "Track a role from All openings to see it here."}</p>
              </div>}
              {view === "Browse" && <div ref={sentinel} className="feed-end">
                {retry ? <button onClick={() => loadMore.current()}>Retry loading openings</button>
                  : loading && jobs.length > 0 && <span role="status">Loading more openings…</span>}
              </div>}
            </section>}
            {selected ? <section className="detail" aria-label="Posting details" hidden={expandedPane === "list"}>
              <div className="detail-header">
                <span>Posting details</span>
                <div className="pane-actions">
                  <button type="button" onClick={() => setCatalogFocus(expandedPane === "details" ? null : "details")}
                    aria-label={expandedPane === "details" ? "Exit full-page posting details" : "Expand posting details"}
                    title={expandedPane === "details" ? "Exit full page" : "Expand posting details"}>
                    {expandedPane === "details" ? <Minimize2 size={15} aria-hidden="true" /> : <Maximize2 size={15} aria-hidden="true" />}
                  </button>
                  <button onClick={closeDetails}>Close</button>
                </div>
              </div>
              <div className="posting-content">
              {detail?.id === selected ? <>
                <p className="eyebrow">{detail.company}</p><h2>{detail.title}</h2>
                <p className="muted">{detail.location || "Location unspecified"}</p>
                <dl className="job-facts">{detail.posted_on && <div><dt>Posted</dt><dd>{formatDate(detail.posted_on + "T12:00:00")}</dd></div>}<div><dt>First seen</dt><dd>{formatDate(detail.first_seen)}</dd></div>
                  <div><dt>Last seen</dt><dd>{formatDate(detail.last_seen)}</dd></div>
                  <div><dt>Source</dt><dd>{sourceLabel(detail.source)}</dd></div>
                  {detail.term && <div><dt>Term</dt><dd>{detail.term}</dd></div>}</dl>
                {!detail.active && <p className="notice">This posting is no longer listed by its source.</p>}
                {coverage.find(source => source.id === detail.source)?.stale &&
                  <p className="notice">The latest source check failed. Confirm this opening on the employer site.</p>}
                <a className="button primary" target="_blank" rel="noreferrer" href={detail.url}>Original posting</a>
                {detail.description && <section className="posting-section"><h3>Job description</h3><PostingText text={detail.description} /></section>}
                {detail.versions && detail.versions.length > 1 && <details><summary>Posting changes</summary>
                  <PostingDiff job={detail} /></details>}
                {owner && <div className="actions posting-actions"><button onClick={()=>navigate("Referrals",{company:detail.company,team:detail.title.slice(0,120)})}>Find people at {detail.company} on LinkedIn</button>
                {profile && <button className="button primary" onClick={() => navigate("Materials",{job: detail.id})}>{currentApplication ? "Open application materials" : "Track and prepare application"}</button>}</div>}
              </> : detailError ? <p role="alert">{detailError}</p> : <p role="status">Loading posting…</p>}
              </div>
            </section> : null}
          </div>
        </>}
      </main>
    </div>
  </>;
}

function Coverage({sources}: {sources: CatalogSource[]}) {
  const [showBoards, setShowBoards] = useState(false);
  return <section className="coverage">
    <PageHeader title="Sources" />
    {!sources.length && <p role="status">Waiting for the first collection run.</p>}
    {[
      {label: "Employer feeds", matches: (source: CatalogSource) => source.status !== "reference"
        && !source.id.startsWith("boards:") && !source.id.startsWith("ats:") && source.kind !== "yc" && source.kind !== "board_index"},
      {label: "Job boards and lists", matches: (source: CatalogSource) => source.id.startsWith("boards:")},
      {label: "Employer board indexes", matches: (source: CatalogSource) => source.kind === "board_index"},
      {label: "Discovered employer boards", matches: (source: CatalogSource) => source.id.startsWith("ats:")},
    ].map(({label, matches}) => {
      const entries = sources.filter(matches);
      if (!entries.length) return null;
      const learned = label === "Discovered employer boards";
      return <section className="source-group" key={label}><h2>{label}</h2>
        {learned && <p className="muted">{entries.filter(source => source.recent_count > 0).length.toLocaleString()} with recent openings · {entries.filter(source => !source.last_attempt).length.toLocaleString()} awaiting first check</p>}
        {learned && <button aria-expanded={showBoards} onClick={() => setShowBoards(!showBoards)}>
          {showBoards ? "Hide" : "Show"} {entries.length} employer boards</button>}
        {(!learned || showBoards) && <ul className="coverage-list">
        {entries.map(source => {
          const homepage = source.homepage || sourceLinks[source.id];
          const status = {current: "Current", failed: source.note || "Last check failed", waiting: "Waiting", setup: "JobSpy setup required",
            reference: source.note || "Reference"}[source.status];
          return <li key={source.id}>
            {source.status !== "reference" && <span className={source.stale ? "source-dot warning" :
              source.status === "current" ? "source-dot" : "source-dot waiting"} />}
            <div><strong>{source.label}</strong><div className="muted">{status}
              {source.last_success && ` · ${source.count} ${source.kind === "board_index" ? "boards" : "roles"} at last success · ${formatDate(source.last_success)}`}
              {source.recent_count > 0 && ` · ${source.recent_count} recent openings`}</div></div>
            {homepage && <a className="button" href={homepage} target="_blank" rel="noreferrer">Open source</a>}
          </li>;
        })}
      </ul>}</section>;
    })}
  </section>;
}

function PostingDiff({job}: {job: Job}) {
  const previous = job.versions?.[1]?.payload.description || "";
  const current = job.description || "";
  if (previous === current) return <p className="muted">Posting metadata changed. The description is unchanged.</p>;
  let prefix = 0;
  let suffix = 0;
  while (prefix < Math.min(previous.length, current.length) && previous[prefix] === current[prefix]) prefix++;
  while (suffix < Math.min(previous.length, current.length) - prefix
    && previous[previous.length - suffix - 1] === current[current.length - suffix - 1]) suffix++;
  return <div className="diff"><del>{previous.slice(prefix, previous.length - suffix)}</del>
    <ins>{current.slice(prefix, current.length - suffix)}</ins></div>;
}

createRoot(document.getElementById("root")!).render(<ThemeProvider><App /></ThemeProvider>);
