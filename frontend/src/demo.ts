import {dateKey, moveDate, type AnalyticsReport} from "./Analytics";
import type {OverviewStats} from "./Overview";
import {ApiError, type Alert, type Application, type CatalogSource, type Details, type Document, type Job, type Profile} from "./api";

const sources: Record<string, string> = {employers: "Employer boards", indeed: "Indeed", lists: "Internship collections"};
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
  {title: "Embedded Systems Co-op", company: "Clearwater Instruments", location: "Burnaby, BC", stage: "preparing",
    source: "indeed", description: "Write firmware for a sensor board and validate communication and timing on real hardware."},
  {title: "Aerospace Test Intern", company: "Highwater Aviation", location: "Richmond, BC", stage: "closed",
    source: "lists", description: "Run environmental tests on aircraft components and document results for the design team."},
  {title: "Data Engineering Intern", company: "Pine Signal", location: "Toronto, ON", stage: "",
    source: "lists", description: "Build test data pipelines and data quality reports for an engineering operations team."},
  {title: "Manufacturing Co-op", company: "Kiteworks Dynamics", location: "Calgary, AB", stage: "",
    source: "employers", description: "Design production aids and help validate new work instructions on the shop floor."},
  {title: "Thermal Engineering Intern", company: "Northline Motion", location: "Seattle, WA", stage: "",
    source: "indeed", description: "Model thermal performance and help run temperature tests on electromechanical assemblies."},
] as const;

const today = dateKey(new Date());
const now = new Date().toISOString();
const ages = [0, 1, 2, 4, 6, 8, 11, 14, 20, 28];
const jobs: Job[] = roles.map((role, index) => {
  const id = "sample-role-" + (index + 1);
  const posted = moveDate(today, -ages[index]);
  const stamp = posted + "T17:00:00Z";
  return {id, title: role.title, company: role.company, location: role.location, source: role.source,
    url: "/demo/jobs?job=" + id, requisition: String(4010 + index), active: 1,
    posted_on: posted, first_seen: stamp, last_seen: now, term: "Summer 2027",
    description: "## About the role\n\n" + role.description +
      "\n\n## Qualifications\n\n- Currently enrolled in a relevant degree program\n- Available for a four-month summer term\n- Comfortable working on a cross-functional team"};
});
const applications: Application[] = jobs.flatMap((job, index) => roles[index].stage ? [{
  id: "sample-application-" + (index + 1), job_id: job.id, title: job.title, company: job.company,
  location: job.location, status: roles[index].stage, notes: index === 0 ? "Review the final PDFs before applying." : "", deadline: "",
}] : []);
const alerts: Alert[] = [jobs[7], jobs[8], jobs[9]].map(job => ({
  job_id: job.id, title: job.title, company: job.company, created_at: job.first_seen, read: 0,
}));
let profile: Profile = {
  watchlist: ["Harbour Robotics", "Clearwater Instruments"],
  searches: [{name: "Mechanical and robotics co-ops", keywords: "mechanical, robotics", location: "", term: "", preferred: "", alerts: true}],
  experience: "Mechanical engineering student with experience designing test fixtures and validating prototypes.",
  skills: ["CAD", "prototype validation", "firmware"],
  referral_school: "University of British Columbia, UBC",
  referral_experience: "prototype development",
  referral_priority: "experience",
  resume_repo: "", resume_branch: "main", resume_entry: "main.tex", cover_repo: "", cover_branch: "main", cover_entry: "main.tex",
};
let preferences = {auto_shortlist: true, draft: false, threshold: 75, smart: true, prepare: true,
  max_experience_years: 2, reject_no_sponsorship: false, minimum_annual_pay: 0};
let intervalMinutes = 5;
const due = new Date(Date.now() + 6 * 60 * 60 * 1000).toISOString();
const reply = {id: 1, subject: "Hardware Test Intern interview invitation", sender: "recruiting@clearwater.example",
  body: "Hi Alex, we'd like to schedule an interview for the Hardware Test Intern role. Let us know your availability.",
  kind: "Interview", applied: 1, application_id: applications[1].id, created: jobs[1].first_seen, due, link: "", done: 0};
const contacts = [{id: "sample-contact-1", name: "Jamie Chen", company: jobs[0].company, stage: "Saved"}];
const sourceRows: CatalogSource[] = Object.entries(sources).map(([id, label]) => {
  const count = jobs.filter(job => job.source === id).length;
  return {id, label, count, recent_count: count, status: "current", last_success: now, last_attempt: now,
    stale: false, note: null, homepage: null, kind: id === "employers" ? "greenhouse" : "jobspy"};
});
const disciplines: Record<string, RegExp> = {Mechanical: /mechanical|thermal|product design/i, Hardware: /hardware|embedded/i,
  Robotics: /robotics/i, Manufacturing: /manufacturing/i, Aerospace: /aerospace/i, Software: /software|embedded/i, "Data & AI": /data/i};
const docs: Document[] = [
  {id: "sample-resume", kind: "resume", entry: "main.tex", compiled: 1, commit_sha: "demo001", created_at: now, verified: 1},
  {id: "sample-cover", kind: "cover", entry: "main.tex", compiled: 1, commit_sha: "demo002", created_at: now, verified: 1},
];
const letter = {id: "sample-letter", created_at: now, content: "Dear hiring team,\n\nI am interested in the Mechanical Design Co-op. My experience building fixtures and validating prototypes would help me contribute to your team."};
const sourceText = new Map(docs.map(doc => [doc.id,
  "\\documentclass{article}\n\\begin{document}\n\\section*{" + (doc.kind === "resume" ? "Alex Morgan" : "Cover letter") +
    "}\nDesigned test fixtures and validated mechanical prototypes.\n\\end{document}\n"]));
sourceText.set("sample-resume-base", sourceText.get("sample-resume")!.replace(
  "Designed test fixtures and validated mechanical prototypes.", "Helped test prototype assemblies."));

function demoData(today: string) {
  const discovered = Array.from({length: 14}, (_, index) => jobs.filter(job => job.posted_on === moveDate(today, index - 13)).length);
  const applied = [0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0];
  const activity = Array.from({length: 14}, (_, index) => ({
    date: moveDate(today, index - 13), applied: applied[index], interview: Number(index === 5 || index === 12),
    offer: Number(index === 11), closed: Number(index === 8), assessment: Number(index === 10), active: Math.floor(index / 4),
  }));
  const pipeline = Object.fromEntries(["shortlisted", "preparing", "ready", "applied", "interview", "offer", "closed"]
    .map(status => [status, applications.filter(item => item.status === status).length]));
  const overview: OverviewStats = {
    totals: {openings: jobs.length, employers: new Set(jobs.map(job => job.company)).size,
      week: discovered.slice(-7).reduce((sum, value) => sum + value, 0)},
    sources: sourceRows.map(({id, count}) => ({source: id, count})).sort((a, b) => b.count - a.count),
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

function openings(query: URLSearchParams) {
  const get = (key: string) => (query.get(key) ?? "").trim().toLowerCase();
  const term = get("term");
  const source = get("source");
  const discipline = disciplines[query.get("discipline") ?? ""];
  const within = Math.min(30, Math.max(1, Number(get("posted_within")) || 30));
  const earliest = moveDate(today, 1 - within);
  const saved = query.has("saved_search") ? profile.searches[Number(get("saved_search"))] : undefined;
  const found = jobs.filter(job => {
    const title = job.title.toLowerCase();
    return (job.posted_on ?? "") >= earliest && (job.posted_on ?? "") <= today &&
      (title + " " + job.company.toLowerCase()).includes(get("q")) &&
      job.location.toLowerCase().includes(get("location")) &&
      (!term || job.term?.toLowerCase() === term) && (!source || source === job.source) &&
      (!discipline || discipline.test(job.title)) &&
      (get("watchlist") !== "true" || profile.watchlist.includes(job.company)) &&
      (!saved || (!saved.keywords || saved.keywords.toLowerCase().split(",").some(word => title.includes(word.trim()))) &&
        job.location.toLowerCase().includes(saved.location.toLowerCase()) &&
        (!saved.term || job.term?.toLowerCase() === saved.term.toLowerCase()));
  });
  const offset = Math.max(0, Number(get("offset")) || 0);
  const limit = get("map_view") === "true" ? 2500 : 100;
  return {jobs: found.slice(offset, offset + limit), has_more: found.length > offset + limit,
    total: found.length, disciplines: Object.keys(disciplines)};
}

function applicationDetails(id: string): Details {
  const app = applications.find(item => item.id === id);
  const job = jobs.find(item => item.id === app?.job_id);
  if (!app || !job) throw new ApiError(404, "Sample application does not exist.");
  return {posting: job, documents: job.id === jobs[0].id ? docs : [], cover_letters: job.id === jobs[0].id ? [letter] : [],
    history: [{event: "Saved as " + app.status, at: job.first_seen}], ai: []};
}

function sampleSkills(job: Job) {
  const text = (job.title + " " + (job.description ?? "")).toLowerCase();
  return (profile.skills ?? []).filter(skill => text.includes(skill.toLowerCase()));
}

export function demoRequest(path: string, method: string, body?: object): unknown {
  const {pathname, searchParams: query} = new URL(path, window.location.origin);
  const route = pathname.replace(/^\/api\/owner\//, "/");
  if (method === "GET") {
    switch (route) {
      case "/api/session": return {owner: true, login_available: false, account: {name: "Alex Morgan", email: "alex@example.com"}};
      case "/api/sources": return sourceRows;
      case "/api/jobs": return openings(query);
      case "/api/analytics": return demoData(today).overview;
      case "/analytics": return demoData(today).report(query.get("end") || today, Number(query.get("days")) || 7);
      case "/worker-login": return {status: "connected", checked: new Date().toISOString()};
      case "/applications": return applications;
      case "/settings": return profile;
      case "/alerts": return alerts;
      case "/reminders": return reply.done ? [] : [{id: reply.id, subject: reply.subject, due: reply.due}];
      case "/priorities": return [
        ...(reply.done ? [] : [{view: "Replies", id: String(reply.id), title: reply.subject, label: reply.kind, due: reply.due}]),
        ...applications.filter(item => item.status === "ready").map(item =>
          ({view: "Materials", id: item.job_id, title: item.title, label: "Ready to submit"})),
      ];
      case "/templates": return docs;
      case "/replies": return {items: [reply], mail: true, sync: {status: "Last check completed", checked: now}};
      case "/mail": return {accounts: [{provider: "Gmail", address: "alex@example.com"}], legacy: false,
        sync: {status: "Last check completed", checked: now}};
      case "/interviews": return applications.filter(item => item.job_id === jobs[1].id || item.status === "offer")
        .map(item => ({...item, interviewed_at: jobs[1].first_seen, invitations: item.job_id === jobs[1].id ? [reply] : []}));
      case "/referrals": return {contacts};
      case "/referrals/people": return {partial: false, school: profile.referral_school?.split(",")[0], people: query.get("company") ? [{
        name: "Taylor Patel", url: "https://example.com", headline: "Mechanical Design Engineer",
        snippet: "Works in prototype development · UBC alum", team_match: true,
        school_match: /\bUBC\b|University of British Columbia/i.test(profile.referral_school ?? ""),
        experience_matches: (profile.referral_experience ?? "").split(",").map(term => term.trim()).filter(term =>
          term && "works in prototype development".includes(term.toLowerCase())),
      }] : []};
      case "/screening": return {preferences, reviews: [{id: jobs[0].id, title: jobs[0].title, company: jobs[0].company,
        verdict: "apply", score: 89, summary: "Fixture design and prototype testing match the role.", matched_skills: sampleSkills(jobs[0])}],
      roles: jobs.slice(0, 5).map((job, index) => {
        const matched_skills = sampleSkills(job);
        const bonus = Math.min(profile.scoring?.skill_cap ?? 30, (profile.scoring?.skill ?? 10) * matched_skills.length);
        return {...job, score: Math.min(100, 65 - index * 5 + bonus), reasons: ["Matches your engineering interests"], matched_skills};
      })};
      case "/background": return {worker: {status: "connected"}, usage: demoData(today).report(today, 7).usage,
        collection: {interval_minutes: intervalMinutes, requested: 0, started: now, finished: now},
        tasks: [{id: "sample-task", status: "done", title: jobs[0].title, company: jobs[0].company, job_id: jobs[0].id}]};
    }
    const job = jobs.find(item => route === "/api/jobs/" + item.id);
    if (job) return {...job, matched_skills: sampleSkills(job),
      contacts: contacts.filter(person => person.company === job.company), versions: []};
    const appId = /^\/applications\/([^/]+)$/.exec(route)?.[1];
    if (appId) return applicationDetails(appId);
    const docId = /^\/documents\/([^/]+)\/source$/.exec(route)?.[1];
    if (docId && sourceText.has(docId)) {
      const parent = docId === "sample-resume" ? "sample-resume-base" : null;
      return {name: "main.tex", content: sourceText.get(docId), tree: [{path: "main.tex", editable: true}],
        checks: {pages: 1, overfull: 0}, parent, ancestors: parent ? [parent] : []};
    }
    throw new ApiError(404, "Sample data is unavailable for this item.");
  }
  if (method === "POST") {
    if (route === "/auth/logout") return {redirect: "/"};
    if (route === "/alerts/read") {alerts.forEach(alert => {alert.read = 1;}); return {ok: true};}
    if (route === "/background/run") return {queued: true};
    if (route === "/mail/check") return {status: "Sample inbox checked."};
  }
  if (method === "PUT") {
    if (route === "/settings" && body) {profile = {...profile, ...body}; return profile;}
    if (route === "/screening" && body) {preferences = {...preferences, ...body}; return preferences;}
    if (route === "/background/schedule") {intervalMinutes = Number(query.get("minutes")) || 5; return {interval_minutes: intervalMinutes};}
    if (route === "/replies/1" && body) {Object.assign(reply, body); return {ok: true};}
    const id = /^\/jobs\/([^/]+)\/application$/.exec(route)?.[1];
    const job = jobs.find(item => item.id === id);
    if (job && body) {
      let app = applications.find(item => item.job_id === job.id);
      if (!app) {
        app = {id: "sample-application-" + job.id, job_id: job.id, title: job.title,
          company: job.company, location: job.location, status: "shortlisted", notes: "", deadline: ""};
        applications.push(app);
      }
      Object.assign(app, body);
      return {id: app.id};
    }
  }
  throw new ApiError(403, "This action needs a connected workspace. Demo data stays in this tab.");
}
