import {useEffect, useState} from "react";
import {api} from "./api";
import {PageHeader} from "./PageHeader";

type Interview = {
  id: string; job_id: string; title: string; company: string; location: string; status: string; interviewed_at: string;
  invitations: {id: number; subject: string; created: string; due: string | null; link: string; done: number}[];
};

export function Interviews({open, openEmail}: {open: (job: string) => void; openEmail: (reply: string) => void}) {
  const [items, setItems] = useState<Interview[]>();
  const [query, setQuery] = useState("");
  const [outcome, setOutcome] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void api<Interview[]>("/api/owner/interviews", "GET", undefined, controller.signal)
      .then(setItems).catch(error => {if (!controller.signal.aborted) setError(error.message);});
    return () => controller.abort();
  }, []);
  const matches = items?.filter(item => (!outcome || item.status === outcome) &&
    (item.title + " " + item.company).toLowerCase().includes(query.toLowerCase().trim()));
  return <section className="desk-page jobs-page">
    <PageHeader title="Interviews" />
    <div className="report-controls">
      <input type="search" aria-label="Search interviews" placeholder="Search company or role" value={query}
        onChange={e => setQuery(e.target.value)} />
      <select aria-label="Filter interview outcomes" value={outcome} onChange={e => setOutcome(e.target.value)}>
        <option value="">All outcomes</option><option value="interview">Interviewing</option>
        <option value="offer">Offer</option><option value="closed">Closed</option>
      </select>
    </div>
    {error && <p role="alert">{error}</p>}
    {!items && !error && <p role="status">Loading interviews…</p>}
    {matches?.length === 0 && <p className="muted">{items?.length ? "No interviews match your filters." : "No interviews recorded yet."}</p>}
    {matches?.map(item => <section className="desk-card interview-card" key={item.id}>
      <div className="panel-heading">
        <div><h2>{item.title}</h2><p className="muted">{item.company}{item.location && " · " + item.location}</p></div>
        <span>{item.status === "interview" ? "Interviewing" : item.status.charAt(0).toUpperCase() + item.status.slice(1)}</span>
      </div>
      <p>First recorded {new Date(item.interviewed_at).toLocaleDateString()}</p>
      {item.invitations.length > 0 && <ul className="interview-invitations">
        {item.invitations.map(invitation => <li key={invitation.id}>
          <div><strong>{invitation.subject}</strong><small>
            {new Date(invitation.created).toLocaleDateString()}{invitation.due && " · " + new Date(invitation.due).toLocaleString()}
            {invitation.done ? " · Done" : ""}</small></div>
          <div className="actions">
            {invitation.link && <a className="button" href={invitation.link} target="_blank" rel="noreferrer">Open link</a>}
            <button onClick={() => openEmail(String(invitation.id))}>Open email</button>
          </div>
        </li>)}
      </ul>}
      <button onClick={() => open(item.job_id)}>Open application</button>
    </section>)}
  </section>;
}
