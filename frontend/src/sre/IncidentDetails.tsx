import { Accordion, AccordionItem, Button, InlineNotification, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Tile } from "@carbon/react";
import { ArrowLeft } from "@carbon/icons-react";
import { APIClient, APIError } from "../api";
import { isUUID } from "./contracts";
import { assessService, recoveryVerification } from "./status";
import { EmptyState, EvidenceBoundary, failure, requireReadAuthorization, RetrievalTime, SREHeading, SRELoading, SREProblem, SRETime, StateTag, unwrap, useBusy, useNow, useRead } from "./shared";

export function IncidentDetails({ id, client, refresh, onRefresh, onBack, onBusy }: {
  id: string; client: APIClient; refresh: number; onRefresh: () => void; onBack: () => void; onBusy: (value: boolean) => void;
}) {
  const now = useNow();
  const state = useRead(async () => {
    if (!isUUID(id)) throw new APIError(422);
    const results = await Promise.allSettled([
      client.sreIncident(id), client.sreEvents(id), client.sreEvidence(id), client.sreServices(),
    ]);
    requireReadAuthorization(results);
    const incident = unwrap(results[0])?.data;
    if (!incident) throw failure(results[0]);
    let evidence = unwrap(results[2])?.data;
    let evidenceError = failure(results[2]);
    if (evidence && (evidence.run.id !== incident.run_id || evidence.run.service_id !== incident.service_id)) {
      evidence = undefined; evidenceError = new APIError(502);
    }
    return {
      incident, evidence, evidenceError, events: unwrap(results[1])?.data,
      eventError: failure(results[1]), services: unwrap(results[3])?.data ?? [],
      serviceError: failure(results[3]),
    };
  }, [client, refresh, id]);
  useBusy(state.loading, onBusy);
  const data = state.data;
  const assessment = data ? assessService(data.incident, data.evidence, now) : undefined;
  const verification = data ? recoveryVerification(data.incident, data.evidence, now) : undefined;
  const events = data?.events ? [...data.events].sort((a, b) => a.sequence - b.sequence) : undefined;
  const latestEvent = events?.at(-1);
  const inconsistent = data && latestEvent && (latestEvent.sequence > data.incident.version || latestEvent.to_state !== data.incident.state);
  return <section className="sre-workspace" aria-label="Incident Details">
    <Button kind="ghost" size="sm" renderIcon={ArrowLeft} onClick={onBack}>Back to Incident Center</Button>
    <SREHeading title="Incident Details">Trace the observations, decisions, and verification recorded for this incident.</SREHeading>
    <EvidenceBoundary />
    {state.loading ? <SRELoading /> : state.error ? <SREProblem error={state.error} onRetry={onRefresh} /> : data && assessment && verification && <>
      {inconsistent && <InlineNotification kind="warning" hideCloseButton lowContrast title="Records changed during retrieval" subtitle="The timeline and lifecycle differ. Refresh to confirm the latest records; recovery is not inferred from a single status." />}
      <Tile className="sre-incident-summary">
        <div className="sre-incident-title"><div><p className="eyebrow">{data.incident.severity} · CONTROLLED DEPENDENCY FAILURE</p><h2>{data.incident.title}</h2>
          <code className="sre-record-id">{data.incident.id}</code></div><StateTag state={data.incident.state} /></div>
        <p className="sre-space"><a href={"#/scout/incidents/" + encodeURIComponent(data.incident.id)}>Investigate with Scout</a></p>
        <dl className="sre-facts sre-metadata">
          <div><dt>Service</dt><dd>{data.services.find(service => service.id === data.incident.service_id)?.service_key ?? data.incident.service_id}</dd></div>
          <div><dt>Detected</dt><dd><SRETime value={data.incident.detected_at} /></dd></div>
          <div><dt>Acknowledged</dt><dd><SRETime value={data.incident.acknowledged_at} /></dd></div>
          <div><dt>Resolved</dt><dd><SRETime value={data.incident.resolved_at} /></dd></div>
          <div><dt>Policy</dt><dd><code>{data.incident.policy_version}</code></dd></div>
          <div><dt>Record version</dt><dd>{data.incident.version}</dd></div>
        </dl>
      </Tile>
      {data.serviceError && <SREProblem error={data.serviceError} title="Service names unavailable; identifiers are shown" />}
      <div className="sre-detail-grid">
        <Tile className="sre-panel"><div className="panel-title"><h2>Current evidence assessment</h2><StateTag state={assessment.state} /></div>
          <p>{assessment.reason}</p><p className="support sre-space">Latest observation <SRETime value={assessment.probe?.observed_at} />.</p>
          <p className="support">Freshness is checked against the browser clock. This exercise does not provide continuous monitoring.</p>
        </Tile>
        <Tile className="sre-panel"><div className="panel-title"><h2>Recovery verification</h2><StateTag state={verification.label} /></div>
          <p>{verification.description}</p>
          <p className="support sre-space">An action being applied does not by itself prove recovery.</p>
        </Tile>
      </div>
      {data.evidenceError ? <SREProblem error={data.evidenceError} title="Diagnostic evidence unavailable" onRetry={onRefresh} /> : data.evidence && <>
        <Tile className="sre-panel">
          <div className="panel-title"><h2>HTTP observations</h2><span className="support">{data.evidence.probes.length} recorded probes</span></div>
          <p className="support">Actual responses to the controlled application dependency. Times below are observations, not retrieval times.</p>
          {!data.evidence.probes.length ? <EmptyState title="No HTTP observations recorded">No health conclusion can be drawn.</EmptyState> : <>
            <ol className="sre-probe-sequence" aria-label="Recorded HTTP response sequence">{data.evidence.probes.map((probe, index) =>
              <li key={probe.id} className={probe.outcome === "HEALTHY" && probe.http_status === 200 ? "sre-probe-ok" : probe.outcome === "HTTP_503" ? "sre-probe-error" : "sre-probe-unknown"}
                title={probe.observed_at + " · " + probe.outcome}><small>{index + 1}</small><b>{probe.http_status ?? "—"}</b><span>{probe.phase.toLowerCase()}</span></li>
            )}</ol>
            <div className="table-scroll sre-table-scroll" tabIndex={0} role="region" aria-label="HTTP observations table">
              <Table size="lg" aria-label="HTTP observations"><TableHead><TableRow>{["Observed", "Phase", "HTTP", "Outcome", "Duration", "Probe ID"].map(value => <TableHeader key={value}>{value}</TableHeader>)}</TableRow></TableHead>
                <TableBody>{data.evidence.probes.map(probe => <TableRow key={probe.id}>
                  <TableCell><SRETime value={probe.observed_at} /></TableCell><TableCell>{probe.phase}</TableCell>
                  <TableCell>{probe.http_status ?? "No response"}</TableCell><TableCell>{probe.outcome.replaceAll("_", " ")}</TableCell>
                  <TableCell>{probe.duration_ms} ms</TableCell><TableCell><code>{probe.id}</code></TableCell>
                </TableRow>)}</TableBody></Table>
            </div>
          </>}
        </Tile>
        <Tile className="sre-panel"><div className="panel-title"><h2>Recovery attempts</h2><span className="support">Execution and verification are distinct</span></div>
          {!data.evidence.recovery_attempts.length ? <p className="support">No recovery attempt recorded.</p> :
            <div className="sre-attempts">{data.evidence.recovery_attempts.map(attempt => <article key={attempt.id}>
              <div className="panel-title"><h3>{attempt.action.replaceAll("-", " ")}</h3><StateTag state={attempt.status} /></div>
              <dl className="sre-facts"><div><dt>Attempt</dt><dd><code>{attempt.id}</code></dd></div>
                <div><dt>Started</dt><dd><SRETime value={attempt.started_at} /></dd></div><div><dt>Finished</dt><dd><SRETime value={attempt.finished_at} /></dd></div>
                <div><dt>Action applied in this attempt</dt><dd>{attempt.action_applied ? "Yes" : "No"}</dd></div>
                {attempt.error_code && <div><dt>Recorded error</dt><dd><code>{attempt.error_code}</code></dd></div>}
              </dl>
            </article>)}</div>}
        </Tile>
        <Tile className="sre-panel"><div className="panel-title"><h2>Exercise context</h2><StateTag state={data.evidence.run.status} /></div>
          <dl className="sre-facts sre-metadata"><div><dt>Exercise</dt><dd><code>{data.evidence.run.id}</code></dd></div>
            <div><dt>Scenario</dt><dd>Controlled application-dependency HTTP 503</dd></div>
            <div><dt>Recorded phase</dt><dd>{data.evidence.run.phase}</dd></div>
            <div><dt>Deadline</dt><dd><SRETime value={data.evidence.run.deadline_at} /></dd></div>
            <div><dt>Fault cleared by action</dt><dd><SRETime value={data.evidence.run.fault_cleared_at} /></dd></div>
            <div><dt>Finished</dt><dd><SRETime value={data.evidence.run.finished_at} /></dd></div></dl>
          {data.evidence.run.status === "ACTIVE" && Date.parse(data.evidence.run.deadline_at) <= now &&
            <p className="sre-expired">The exercise deadline has elapsed. Its stored ACTIVE status awaits admin reconciliation; recovery is not assumed.</p>}
          {data.evidence.run.error_code && <p className="support">Recorded error: <code>{data.evidence.run.error_code}</code></p>}
        </Tile>
        <Accordion className="sre-raw-evidence"><AccordionItem title="Diagnostic payloads and correlation IDs">
          <p className="support">Sanitized evidence returned by the API. Request and probe IDs can be matched to timeline events.</p>
          <pre>{JSON.stringify(data.evidence, null, 2)}</pre>
        </AccordionItem></Accordion>
      </>}
      <Tile className="sre-panel"><div className="panel-title"><h2>Event timeline</h2><span className="support">Backend sequence order</span></div>
        {data.eventError ? <SREProblem error={data.eventError} title="Timeline unavailable" onRetry={onRefresh} /> :
          !events?.length ? <p className="support">No timeline events returned.</p> :
            <ol className="sre-timeline">{events.map(event => <li key={event.id}>
              <div className="sre-timeline-marker">{event.sequence}</div><div className="sre-timeline-entry">
                <div className="panel-title"><h3>{event.event_type.replaceAll("_", " ")}</h3><SRETime value={event.created_at} /></div>
                <p>{event.from_state ? event.from_state + " → " : ""}{event.to_state} · {event.actor}</p>
                <Accordion><AccordionItem title={"Event " + event.sequence + " evidence"}><pre>{JSON.stringify({ request_id: event.request_id, ...event.evidence }, null, 2)}</pre></AccordionItem></Accordion>
              </div>
            </li>)}</ol>}
      </Tile>
      <RetrievalTime value={state.retrieved} />
    </>}
  </section>;
}
