import { Button, Tag } from "@carbon/react";
import { Renew } from "@carbon/icons-react";
import { date } from "./format";

const pages = ["Overview", "AI Analyst", "Pipeline"] as const;
export type HeaderPage = typeof pages[number];

export function AppHeader({ page, referenceTime, busy, onNavigate, onRefresh }: {
  page: HeaderPage; referenceTime: string; busy: boolean;
  onNavigate: (page: HeaderPage) => void; onRefresh: () => void;
}) {
  const timestamp = date(referenceTime);
  const separator = timestamp.lastIndexOf(", ");
  return <header className="app-header">
    <a className="brand" href="#" aria-label="InfraSight AI - Overview" onClick={event => { event.preventDefault(); onNavigate("Overview"); }}>
      <span>InfraSight <b>AI</b></span>
    </a>
    <nav className="top-navigation" aria-label="Main navigation">
      {pages.map((name) => {
        return <button key={name} aria-current={page === name ? "page" : undefined} onClick={() => onNavigate(name)}><span>{name === "AI Analyst" ? "Scout" : name}</span></button>;
      })}
    </nav>
    <div className="header-context" title="Latest successful ETL run reference; refresh to check for a newer completed run.">
      <Tag type="blue" size="sm">LIVE</Tag>
      <time className="header-datetime" dateTime={referenceTime}>
        <span>{separator < 0 ? timestamp : timestamp.slice(0, separator)}</span>
        <b>{separator < 0 ? "" : timestamp.slice(separator + 2)}</b>
      </time>
    </div>
    <Button className="header-refresh" hasIconOnly renderIcon={Renew} iconDescription="Refresh analytics" kind="ghost" size="sm" disabled={busy} onClick={onRefresh} />
  </header>;
}
