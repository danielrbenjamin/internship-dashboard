import {demoMode} from "./Routes";
import {demoAsset, demoPdf} from "./demoAssets";

export type Job = {
  id: string; title: string; company: string; location: string; url: string;
  posted_on?: string | null; first_seen: string; last_seen: string; source: string; requisition: string; active: number;
  contacts?:{id:string;name:string}[];term?: string; description?: string; versions?: { fingerprint: string; seen_at: string; payload: { description: string } }[];
};
export type Search = {name: string; keywords: string; location: string; term: string; preferred: string; alerts: boolean};
export type Profile = {
  watchlist: string[]; searches: Search[]; experience: string; resume_repo: string;
  cover_repo?:string;cover_entry?:string;cover_branch?:string;resume_branch: string; resume_entry: string;
};
export type Application = {
  id: string; job_id: string; title: string; company: string; location: string;
  status: string; notes: string; deadline: string; submitted_version?: string;
};
export type Document = {kind?: "resume" | "cover"; entry?: string; id: string; compiled: number; commit_sha: string; created_at: string; verified?: number};
export type CoverLetter = {id: string; content: string; created_at: string};
export type Task = {id: string; status: string; result: string};
export type Details = {
  posting: Job; documents: Document[]; cover_letters: CoverLetter[]; ai: Task[]; history: {event: string; at: string}[];
};
export type Alert = {job_id: string; title: string; company: string; created_at: string; read: number};
export type Source = {id: string; count: number; error: string | null; last_success: string | null};
export type CatalogSource = {
  id: string; label: string; count: number; recent_count: number; stale: boolean; last_success: string | null;
  last_attempt: string | null; homepage: string | null; note: string | null; kind: string;
  status: "current" | "failed" | "waiting" | "setup" | "reference";
};
export const statuses = ["shortlisted", "preparing", "ready", "applied", "interview", "offer", "closed"];
export const formatDate = (date: string) => new Intl.DateTimeFormat(undefined, {month: "short", day: "numeric"}).format(new Date(date));

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

async function request(path: string, method: string, body?: object, signal?: AbortSignal) {
  const response = await fetch(path, {
    method, signal, cache: "no-store",
    headers: body ? {"Content-Type": "application/json"} : undefined,
    body: body ? JSON.stringify(body) : method === "POST" ? "" : undefined,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(response.status, typeof error.detail === "string" ? error.detail : `Request failed (${response.status})`);
  }
  return response;
}

export async function api<T>(path: string, method = "GET", body?: object, signal?: AbortSignal): Promise<T> {
  if (demoMode && !path.startsWith("/map/")) {
    const {demoRequest} = await import("./demo");
    signal?.throwIfAborted();
    return structuredClone(demoRequest(path, method, body)) as T;
  }
  return (await request(path, method, body, signal)).json();
}

export async function pdfPreview(path: string, edit: {before: string; after: string; source_file?: string}) {
  if (demoMode) return demoPdf(path);
  const file = await (await request(path, "POST", edit)).blob();
  if (!file.size || file.type !== "application/pdf") throw new Error("The PDF preview could not be opened.");
  return file;
}
export function assetHref(path: string) {
  return demoMode ? demoAsset(path) : path;
}
