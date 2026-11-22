import {useEffect, useState} from "react";
import {X} from "lucide-react";
import type {Route} from "./Routes";

const steps: {route: Route; title: string; description: string}[] = [
  {route: {view: "Overview"}, title: "Overview", description: "See saved roles, deadlines, and new matches in one place."},
  {route: {view: "Browse", job: "sample-role-1"}, title: "All openings", description: "Filter by date, discipline, or source, then open a job to read the posting."},
  {route: {view: "Screening"}, title: "Where to apply", description: "See why jobs match your searches and skills. Screening preferences control what happens next. The AI label marks actions that use Codex tokens."},
  {route: {view: "Materials", job: "sample-role-1"}, title: "Application materials", description: "Open the sample résumé and cover letter. Compare the prepared version to see what changed."},
  {route: {view: "Referrals", company: "Harbour Robotics"}, title: "Referrals", description: "Find people at an employer and prioritize a team or a school you choose."},
  {route: {view: "Analytics"}, title: "Analytics", description: "See your application trends, discovery numbers, and Tern’s AI usage."},
];

export function DemoTour({navigate, close}: {navigate: (route: Route) => void; close: () => void}) {
  const [index, setIndex] = useState(0);
  const step = steps[index];
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector("dialog:modal, .account-menu:popover-open")) close();
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [close]);
  function go(next: number) {
    setIndex(next);
    navigate(steps[next].route);
  }
  return <aside className="demo-tour" aria-labelledby="demo-tour-heading">
    <div className="panel-heading"><span>Demo tour · {index + 1} of {steps.length}</span>
      <button aria-label="Close demo tour" onClick={close}><X size={15} /></button></div>
    <div aria-live="polite">
      <h2 id="demo-tour-heading">{step.title}</h2><p>{step.description}</p>
    </div>
    <div className="actions">
      <button onClick={close}>Skip tour</button>
      {index > 0 && <button onClick={() => go(index - 1)}>Back</button>}
      <button className="primary" onClick={index + 1 === steps.length ? close : () => go(index + 1)}>
        {index + 1 === steps.length ? "Finish" : "Next"}
      </button>
    </div>
  </aside>;
}
