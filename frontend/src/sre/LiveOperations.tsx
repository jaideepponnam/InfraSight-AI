import { Button, InlineNotification, Tile } from "@carbon/react";
import { APIClient, APIError } from "../api";
import type { DiagnosticEvidence, Incident } from "./types";
import { assessService } from "./status";
import { IncidentTable } from "./IncidentTable";
import { EmptyState, EvidenceBoundary, failure, LifecycleTag, requireReadAuthorization, RetrievalTime, SREHeading, SRELoading, SREProblem, SRETime, StateTag, unwrap, useBusy, useNow, useRead } from "./shared";

export function LiveOperations({ client, refresh, onRefresh, onSelect, onBusy }: {
  client: APIClient; refresh: number; onRefresh: () => void; onSelect: (id: string) => void; onBusy: (value: boolean) => void;
}) {
  const now = useNow();
  const state = useRead(async () => {
    const results = await Promise.allSettled([client.sreServices(), client.sreIncidents({ limit: 100 })]);
    requireReadAuthorization(results);
    const registry = unwrap(results[0]);
    if (!registry) throw failure(results[0]);
    const incidents = unwrap(results[1]);
    const latest = new Map<string, Incident>();
    for (const incident of incidents?.data ?? []) if (!latest.has(incident.service_id)) latest.set(incident.service_id, incident);
    const selected = registry.data.slice(0, 12);
    const responses = await Promise.allSettled(selected.map(async service => {
      const incident = latest.get(service.id);
      if (!incident) return undefined;
      const response = await client.sreEvidence(incident.id);
      if (response.data.run.id !== incident.run_id || response.data.run.service_id !== service.id) throw new APIError(502);
      return response.data;
    }));
    requireReadAuthorization(responses);
    const evidence = new Map<string, DiagnosticEvidence>();
    const errors = new Map<string, APIError>();
    responses.forEach((result, index) => {
      const value = unwrap(result);
      if (value) evidence.set(selected[index].id, value);
      const error = failure(result);
      if (error) errors.set(selected[index].id, error);
    });
    return { services: registry.data, incidents, incidentError: failure(results[1]), latest, evidence, errors };
  }, [client, refresh]);
  useBusy(state.loading, onBusy);
  const data = state.data;
  const observations = data?.services.map(service => assessService(data.latest.get(service.id), data.evidence.get(service.id), now)) ?? [];
  return <section className="sre-workspace" aria-label="Live Operations">
    <SREHeading title="Live Operations">Service observations and incident context, with evidence freshness made explicit.</SREHeading>
    <EvidenceBoundary />
    {state.loading ? <SRELoading /> : state.error ? <SREProblem error={state.error} onRetry={onRefresh} /> : data && <>
      <div className="sre-metrics">
        <Tile><span className="metric-label">Registered services</span><strong>{data.services.length}</strong><small>Returned by the service registry</small></Tile>
        <Tile><span className="metric-label">Fresh observations</span><strong>{observations.filter(value => value.state === "HEALTHY" || value.state === "DEGRADED").length}</strong><small>Within the 15-second observation window</small></Tile>
        <Tile><span className="metric-label">Open in loaded records</span><strong>{data.incidents ? data.incidents.data.filter(incident => incident.state !== "RESOLVED").length : "Unavailable"}</strong><small>From {data.incidents?.data.length ?? "unavailable"} loaded incident records</small></Tile>
        <Tile><span className="metric-label">Recorded incidents</span><strong>{data.incidents?.meta.total ?? "Unavailable"}</strong><small>Stored lifecycle records, not an outage count</small></Tile>
      </div>
      {data.incidentError && <SREProblem error={data.incidentError} title="Incident summaries unavailable" onRetry={onRefresh} />}
      {(data.incidents?.meta.total ?? 0) > 100 && <InlineNotification kind="info" hideCloseButton lowContrast title="Bounded incident context" subtitle="Service context uses the newest 100 incidents. Older records remain available in Incident Center; services without loaded evidence stay unknown." />}
      {data.services.length > 12 && <p className="support">Evidence retrieval is limited to the first 12 registered services. Other services remain unknown.</p>}
      {data.services.length === 0 ? <EmptyState title="No monitored services returned">The backend has not registered an SRE service. This view does not create services or start an exercise.</EmptyState> :
        <div className="sre-service-grid">{data.services.map(service => {
          const incident = data.latest.get(service.id);
          const assessment = assessService(incident, data.evidence.get(service.id), now);
          return <Tile key={service.id} className={"sre-service sre-state-" + assessment.state.toLowerCase()}>
            <div className="panel-title"><h2>{service.service_key}</h2><StateTag state={assessment.state} /></div>
            <p className="support">{service.description}</p>
            <p className="sre-assessment">{assessment.reason}</p>
            {data.errors.has(service.id) && <SREProblem error={data.errors.get(service.id)!} title="Service evidence unavailable" />}
            <dl className="sre-facts">
              <div><dt>Latest HTTP observation</dt><dd><SRETime value={assessment.probe?.observed_at} /></dd></div>
              <div><dt>Last recorded response</dt><dd>{assessment.probe ? (assessment.probe.http_status ?? "No HTTP response") + " · " + assessment.probe.outcome.replaceAll("_", " ") : "No observation available"}</dd></div>
              <div><dt>Most recent incident in loaded records</dt><dd>{incident ? <LifecycleTag state={incident.state} /> : "None returned; health remains unknown"}</dd></div>
            </dl>
            {incident && <Button kind="tertiary" size="sm" onClick={() => onSelect(incident.id)}>View incident</Button>}
          </Tile>;
        })}</div>}
      <Tile className="sre-panel"><div className="panel-title"><h2>Recent incidents</h2><span className="support">Latest {Math.min(data.incidents?.data.length ?? 0, 5)} loaded records</span></div>
        {data.incidents ? data.incidents.data.length ? <IncidentTable incidents={data.incidents.data.slice(0, 5)} services={data.services} onSelect={onSelect} label="Recent incidents" />
          : <p className="support">No incidents have been returned. This does not establish healthy service operation.</p>
          : <p className="support">Incident records could not be retrieved.</p>}
      </Tile>
      <RetrievalTime value={state.retrieved} />
    </>}
  </section>;
}
