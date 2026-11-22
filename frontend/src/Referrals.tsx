import {useEffect, useState} from "react";
import {FindPeople} from "./FindPeople";
import {PageHeader} from "./PageHeader";
import {api, type Application} from "./api";

export type SavedContact = {id: string; name: string; company: string; linkedin?: string; stage?: string};

export function Referrals({apps, initialCompany, initialTeam}: {
  apps: Application[]; initialCompany: string; initialTeam: string;
}) {
  const [contacts, setContacts] = useState<SavedContact[]>([]);
  const [error, setError] = useState("");
  async function load() {
    const data = await api<{contacts: SavedContact[]}>("/api/owner/referrals");
    setContacts(data.contacts);
  }
  useEffect(() => {void load().catch(error => setError(error.message));}, []);

  return <section className="desk-page">
    <PageHeader title="Referrals" />
    {error && <p role="alert">{error}</p>}
    <FindPeople key={initialCompany + "|" + initialTeam} apps={apps} initialCompany={initialCompany}
      initialTeam={initialTeam} contacts={contacts} reload={load} />
  </section>;
}
