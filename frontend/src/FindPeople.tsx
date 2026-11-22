import {useEffect, useRef, useState} from "react";
import type {SavedContact} from "./Referrals";
import {api, type Application} from "./api";

type Person = {name: string; url: string; headline: string; snippet: string; team_match: boolean; ubc: boolean};
type Results = {people: Person[]; partial: boolean};

export function linkedInPeople(company: string, keywords = "") {
  const url = new URL("https://www.linkedin.com/search/results/people/");
  url.searchParams.set("keywords", [company.trim(), keywords.trim()].filter(Boolean).join(" "));
  return url.href;
}

export function FindPeople({apps, initialCompany, initialTeam, contacts, reload}: {
  apps: Application[]; initialCompany: string; initialTeam: string;
  contacts: SavedContact[]; reload: () => Promise<void>;
}) {
  const [company, setCompany] = useState(initialCompany || apps[0]?.company || "");
  const [team, setTeam] = useState(initialTeam);
  const [results, setResults] = useState<Results & {company: string}>();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState("");
  const [saved, setSaved] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [searchUnavailable, setSearchUnavailable] = useState(false);
  const [searched, setSearched] = useState({employer: "", team: ""});
  const request = useRef(false);
  const companies = [...new Set(apps.map(a => a.company))].sort();

  async function search(employer: string, role: string) {
    if (!employer || request.current) return;
    request.current = true;
    setLoading(true);
    setResults(undefined);
    setMessage("");
    setSearchUnavailable(false);
    setSearched({employer, team: role});
    try {
      const query = new URLSearchParams({company: employer, team: role});
      const response = await api<Results>("/api/owner/referrals/people?" + query);
      setResults({...response, company: employer});
    } catch (error) {
      setSearchUnavailable(true);
      setMessage((error as Error).message);
    } finally {
      setLoading(false);
      request.current = false;
    }
  }

  useEffect(() => {
    if (initialCompany) void search(initialCompany, initialTeam);
  }, [initialCompany, initialTeam]);

  async function save(person: Person, employer: string) {
    setSaving(person.url);
    setMessage("");
    try {
      await api("/api/owner/contacts", "POST", {name: person.name, company: employer, linkedin: person.url});
      setSaved(previous => [...previous, person.url]);
      setMessage(person.name + " saved to Referrals.");
      await reload();
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setSaving("");
    }
  }

  const savedMatches = contacts.filter(contact =>
    contact.company.toLowerCase() === (searched.employer || company.trim()).toLowerCase() &&
    contact.stage !== "Avoid" &&
    !results?.people.some(person => person.url === contact.linkedin?.split(/[?#]/)[0].replace(/\/$/, "")));
  return <section>
    <form className="referral-search jobs-toolbar" onSubmit={event => {
      event.preventDefault();
      void search(company.trim(), team.trim());
    }}>
      <label>Employer<input required maxLength={160} list="referral-employers" value={company} onChange={e => setCompany(e.target.value)} /></label>
      <datalist id="referral-employers">{companies.map(c => <option key={c} value={c} />)}</datalist>
      <label>Team or role<input maxLength={120} value={team} onChange={e => setTeam(e.target.value)} list="referral-teams" placeholder="Optional" /></label>
      <datalist id="referral-teams">{["Mechanical Engineer", "Hardware Engineer", "Robotics Engineer", "University Recruiter"].map(k => <option key={k} value={k} />)}</datalist>
      <button className="primary" disabled={loading || !company.trim()}>{loading ? "Searching…" : "Find people"}</button>
    </form>
    {message && <p role="status">{message}</p>}
    {(searchUnavailable || results?.people.length === 0) && <a className="button"
      href={linkedInPeople(searched.employer, searched.team)} target="_blank" rel="noreferrer">Search LinkedIn directly</a>}
    {!!savedMatches.length && <section className="referral-people" aria-label="Saved contacts">
      {savedMatches.map(contact => <article key={contact.id} className="contact-row">
        <div><strong>{contact.name}</strong><p>{contact.company} · Saved</p></div>
        {contact.linkedin && <a href={contact.linkedin} target="_blank" rel="noreferrer">Profile</a>}
      </article>)}
    </section>}
    {results && <section className="referral-people" aria-label="LinkedIn search results">
      <h3>People matching {results.company}</h3>
      {results.partial && <p role="status">Some searches were unavailable. Showing the results we received.</p>}
      {!results.people.length && <p>No matching public profiles found. Try a shorter employer or team name.</p>}
      {results.people.map(person => {
        const isSaved = [...saved, ...contacts.flatMap(contact => contact.linkedin ? [contact.linkedin] : [])].some(url => url.split(/[?#]/)[0].replace(/\/$/, "") === person.url);
        return <article className="contact-row" key={person.url}>
          <div>
            <strong>{person.name}</strong>
            {person.headline !== person.name && <p>{person.headline.slice(person.name.length).replace(/^\s*[-–—|]\s*/, "")}</p>}
            {(person.team_match || person.ubc) && <p>{[person.team_match && "Team or role match", person.ubc && "UBC mentioned"].filter(Boolean).join(" · ")}</p>}
            {person.snippet && <p>{person.snippet}</p>}
          </div>
          <a href={person.url} target="_blank" rel="noreferrer">Profile</a>
          <button disabled={isSaved || !!saving} onClick={() => void save(person, results.company)}>{isSaved ? "Saved" : saving === person.url ? "Saving…" : "Save contact"}</button>
        </article>;
      })}
    </section>}
  </section>;
}
