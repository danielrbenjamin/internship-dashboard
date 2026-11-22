import type {ReactNode} from "react";

export function PageHeader({title, children, context, className = ""}: {title: string; children?: ReactNode; context?: ReactNode; className?: string}) {
  return <header className={["page-header", className].filter(Boolean).join(" ")}>
    <div>{context && <p className="eyebrow">{context}</p>}<h1>{title}</h1></div>
    {children && <div className="page-actions">{children}</div>}
  </header>;
}
