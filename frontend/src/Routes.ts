import type {View} from "./Navigation";

const paths: Record<View, string> = {
  Overview: "/",
  Demo: "/demo",
  Browse: "/jobs",
  Screening: "/where-to-apply",
  Saved: "/saved",
  Applied: "/applied",
  Interviews: "/interviews",
  Analytics: "/analytics",
  Materials: "/materials",
  Needs: "/needs-you",
  Background: "/background",
  Replies: "/email",
  Referrals: "/referrals",
  Alerts: "/alerts",
  Sources: "/sources",
  Settings: "/settings",
};

export const publicViews: readonly View[] = ["Overview", "Browse", "Sources", "Demo"];
type RouteOptions = {job?: string; tab?: string; company?: string; team?: string; reply?: string};
export type Route = {view: View} & RouteOptions;

export function readRoute(): Route {
  const pathname = window.location.pathname.replace(/\/$/, "") || "/";
  const view = (Object.keys(paths) as View[]).find(key => paths[key] === pathname) ?? "Overview";
  const query = new URLSearchParams(window.location.search);
  const job = query.get("job") ?? "";
  const tab = query.get("tab") ?? "";
  return {
    view,
    job: ["Browse", "Saved", "Applied", "Materials"].includes(view) && /^[\w-]{1,100}$/.test(job) ? job : undefined,
    tab: view === "Settings" && ["Profile", "Discovery", "Email inboxes", "Codex"].includes(tab) ? tab : undefined,
    company: view === "Referrals" ? query.get("company")?.slice(0, 160) : undefined,
    team: view === "Referrals" ? query.get("team")?.slice(0, 120) : undefined,
    reply: view === "Replies" ? query.get("reply") ?? undefined : undefined,
  };
}

export function routeUrl({view, ...options}: Route) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(options)) if (value) query.set(key, value);
  return paths[view] + (query.size ? "?" + query.toString() : "");
}
