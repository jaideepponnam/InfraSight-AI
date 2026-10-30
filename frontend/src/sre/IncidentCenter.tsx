import { useState } from "react";
import { Button, Select, SelectItem, Tile } from "@carbon/react";
import { APIClient } from "../api";
import { INCIDENT_STATES, type IncidentState } from "./types";
import { IncidentTable } from "./IncidentTable";
import { EmptyState, EvidenceBoundary, failure, requireReadAuthorization, RetrievalTime, SREHeading, SRELoading, SREProblem, unwrap, useBusy, useRead } from "./shared";

const PAGE_SIZE = 20;
export function IncidentCenter({ client, refresh, onRefresh, onSelect, onBusy }: {
  client: APIClient; refresh: number; onRefresh: () => void; onSelect: (id: string) => void; onBusy: (value: boolean) => void;
}) {
  const [filter, setFilter] = useState<IncidentState | "ALL">("ALL");
  const [offset, setOffset] = useState(0);
  const state = useRead(async () => {
    const results = await Promise.allSettled([
      client.sreIncidents({ limit: PAGE_SIZE, offset, ...(filter !== "ALL" ? { state: filter } : {}) }),
      client.sreServices(),
    ]);
    requireReadAuthorization(results);
    const incidents = unwrap(results[0]);
    if (!incidents) throw failure(results[0]);
    return { incidents, services: unwrap(results[1])?.data ?? [], serviceError: failure(results[1]) };
  }, [client, refresh, filter, offset]);
  useBusy(state.loading, onBusy);
  return <section className="sre-workspace" aria-label="Incident Center">
    <SREHeading title="Incident Center">Investigate recorded incidents, follow their lifecycle, and inspect the evidence behind recovery.</SREHeading>
    <EvidenceBoundary />
    <div className="sre-list-toolbar"><Select id="sre-incident-state" labelText="Lifecycle status" value={filter}
      onChange={event => { setFilter(event.target.value as IncidentState | "ALL"); setOffset(0); }}>
      <SelectItem value="ALL" text="All statuses" />
      {INCIDENT_STATES.map(value => <SelectItem key={value} value={value} text={value.replaceAll("_", " ")} />)}
    </Select><p className="support">Newest detected first. Lifecycle status is separate from current service health.</p></div>
    {state.loading ? <SRELoading /> : state.error ? <SREProblem error={state.error} onRetry={onRefresh} /> : state.data && <>
      {state.data.serviceError && <SREProblem error={state.data.serviceError} title="Service names unavailable; identifiers are shown" />}
      {!state.data.incidents.data.length ? <EmptyState title={filter === "ALL" ? "No incidents returned" : "No incidents match this status"}>
        {offset ? "This page has no records. Use Previous to return to earlier pages." : "Recorded incidents will appear here when the backend detects them. This read-only page does not start exercises."}
      </EmptyState> : <Tile className="sre-panel"><div className="panel-title"><h2>Incident records</h2><span className="support">{state.data.incidents.meta.total} matching records</span></div>
        <IncidentTable incidents={state.data.incidents.data} services={state.data.services} onSelect={onSelect} />
      </Tile>}
      <div className="sre-pagination" aria-label="Incident pagination"><p className="support">
        {state.data.incidents.data.length ? (offset + 1) + "–" + (offset + state.data.incidents.data.length) : "0"} of {state.data.incidents.meta.total} matching records
      </p><div><Button kind="ghost" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</Button>
        <Button kind="ghost" size="sm" disabled={offset + PAGE_SIZE > 10_000 || offset + PAGE_SIZE >= (state.data.incidents.meta.total ?? 0)} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</Button></div></div>
      {offset === 10_000 && (state.data.incidents.meta.total ?? 0) > offset + PAGE_SIZE && <p className="support">The API pagination window ends here. Select a lifecycle status to narrow the records.</p>}
      <RetrievalTime value={state.retrieved} />
    </>}
  </section>;
}
