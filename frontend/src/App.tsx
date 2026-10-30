import { useEffect, useRef, useState } from "react";
import {
  Accordion,
  AccordionItem,
  Button,
  InlineLoading,
  InlineNotification,
  SkeletonText,
  Select,
  SelectItem,
  Tag,
  TextArea,
  TextInput,
  Tile,
} from "@carbon/react";
import {
  ArrowRight,
  CheckmarkOutline,
  Information,
} from "@carbon/icons-react";
import { APIClient, APIError, contextForRun, live } from "./api";
import { HealthPanel } from "./HealthPanel";
import { AppHeader, type HeaderPage } from "./AppHeader";
import { DemoETLAction } from "./DemoETLAction";
import { DatabaseSample } from "./DatabaseSample";
import { AnalystAnswer } from "./AnalystAnswer";
import { CoverageEvidence } from "./CoverageEvidence";
import { LiveOperations } from "./sre/LiveOperations";
import { IncidentCenter } from "./sre/IncidentCenter";
import { IncidentDetails } from "./sre/IncidentDetails";
import { date, money, numeric, percent, telemetryState } from "./format";
import type { AIResponse, Context, IncidentContext, Overview, Region, Run } from "./types";
import { isUUID } from "./sre/contracts";

export const SUGGESTIONS = [
  "How is our infrastructure doing?",
  "Which servers are expensive but underutilized?",
  "Which region has the most critical infrastructure?",
  "Which servers exceeded 80% CPU?",
  "Did infrastructure cost increase versus the previous period?",
];
type Page = HeaderPage;
type AppRoute = { page: Page; incidentId?: string; investigation?: boolean };
const pageHashes: Record<Page, string> = {
  "Overview": "#/overview", "Live Operations": "#/operations", "Incident Center": "#/incidents",
  "AI Analyst": "#/scout", "Pipeline": "#/pipeline",
};
function currentRoute(): AppRoute {
  const hash = window.location.hash;
  const scout = /^#\/scout\/incidents(?:\/([^/]+))?$/.exec(hash);
  if (scout) return { page: "AI Analyst", investigation: true, incidentId: scout[1] };
  const detail = /^#\/incidents\/([^/]+)$/.exec(hash);
  if (detail) return { page: "Incident Center", incidentId: detail[1] };
  const page = (Object.keys(pageHashes) as Page[]).find(value => pageHashes[value] === hash);
  return { page: page ?? "Overview" };
}
function Notice({ error }: { error: APIError }) {
  return (
    <InlineNotification
      kind={error.status === 429 ? "warning" : "error"}
      title={error.status === 429 ? "Analysis paused" : "Request unavailable"}
      subtitle={error.code === "SRE_DISABLED" ? "SRE investigation is disabled on this backend. Infrastructure analytics remain available." : error.message}
      hideCloseButton
      lowContrast
    />
  );
}
function Heading({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="page-heading">
      <div className="eyebrow">INFRASTRUCTURE INTELLIGENCE</div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </div>
  );
}
function Metric({
  label,
  value,
  note,
  tone = "",
}: {
  label: string;
  value: string | number;
  note: string;
  tone?: string;
}) {
  return (
    <Tile className={"metric " + tone}>
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </Tile>
  );
}
function OverviewView({
  data,
  regions,
  context,
  client,
}: {
  data: Overview;
  regions: Region[];
  context: Context;
  client: APIClient;
}) {
  return (
    <>
      <Heading
        title="Infrastructure Intelligence"
        subtitle="Cloud infrastructure health, utilization and cost intelligence."
      />
      <div className="kpi-grid">
        <Metric
          label="Total servers"
          value={data.inventory_servers}
          note="Registered inventory"
        />
        <Metric
          label="Healthy"
          value={data.healthy_servers}
          note="Fresh at reference time"
          tone="healthy"
        />
        <Metric
          label="Critical"
          value={data.critical_servers}
          note="Requires investigation"
          tone="critical"
        />
        <Metric
          label="Telemetry coverage"
          value={percent(data.coverage.coverage_fraction, true)}
          note="Observation-time coverage"
          tone="analytical"
        />
        <Metric
          label="Observed cost"
          value={money(data.observed_cost, context.currency)}
          note="Selected observation intervals"
        />
      </div>
      <div className="analytics-grid">
        <HealthPanel data={data} regions={regions} context={context} client={client} />
        <Tile className="panel">
          <div className="panel-title">
            <h2>Resource intelligence</h2>
            <Tag type="blue" size="sm">Utilization</Tag>
          </div>
          <p className="support">
            Fresh-server averages. Percentages describe utilization, not
            infrastructure capacity.
          </p>
          <div className="resource-bars">
            {[
              ["CPU", data.average_cpu_percent],
              ["Memory", data.average_memory_percent],
              ["Storage", data.average_storage_percent],
            ].map(([label, value]) => (
              <div className="resource" key={label}>
                <div>
                  <span>{label}</span>
                  <b>{percent(value)}</b>
                </div>
                <div className="track">
                  <span
                    style={{
                      width:
                        Math.min(
                          100,
                          Math.max(0, numeric(value)?.toNumber() || 0),
                        ) + "%",
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
          <div className="fact-list">
            <div>
              <span>Reporting / expected servers</span>
              <b>
                {data.coverage.reporting_server_count} /{" "}
                {data.coverage.expected_server_count}
              </b>
            </div>
            <div>
              <span>Priced observation-time coverage</span>
              <b>{percent(data.coverage.cost_coverage_fraction, true)}</b>
            </div>
            <div>
              <span>Highest CPU server</span>
              <b>{data.highest_cpu_server?.server_name || "Not available"}</b>
            </div>
            <div>
              <span>Highest-cost server</span>
              <b>{data.highest_cost_server?.server_name || "Not available"}</b>
            </div>
          </div>
          <div className="note">
            <Information size={16} />
            <span>
              Coverage measures observation time. It is separate from the count
              of reporting servers.
            </span>
          </div>
        </Tile>
      </div>
    </>
  );
}

export function AIAnalyst({
  client,
  context,
  state,
  contextLoading = false,
  investigation = false,
  incidentId,
  onScopeChange,
}: {
  client: APIClient;
  context: Context;
  state: string;
  contextLoading?: boolean;
  investigation?: boolean;
  incidentId?: string;
  onScopeChange?: (incidents: boolean) => void;
}) {
  const [question, setQuestion] = useState(investigation && incidentId ? "Investigate this incident: explain the HTTP observations, lifecycle events, and recovery verification. Distinguish historical recovery from current health." : "");
  const [selectedId, setSelectedId] = useState(incidentId ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<APIError | null>(null);
  const [result, setResult] = useState<{
    response: AIResponse;
    context: Context | IncidentContext;
    state: string;
  } | null>(null);
  const selectedContext: Context | IncidentContext = investigation
    ? { analysis_scope: "incidents", ...(selectedId.trim() ? { incident_id: selectedId.trim() } : {}) }
    : context;
  const invalidId = investigation && !!selectedId.trim() && !isUUID(selectedId.trim());
  const suggestions = investigation ? [
    "List recorded incidents and their lifecycle status.",
    "Which HTTP observations support this incident?",
    "Explain the recorded lifecycle events for this incident.",
    "Was recovery verified, and does that establish current health?",
    "What remains unknown from the recorded evidence?",
  ] : SUGGESTIONS;
  async function analyze() {
    if (!question.trim() || busy || contextLoading || invalidId) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult({
        response: await client.ask(question, selectedContext),
        context: { ...selectedContext },
        state,
      });
    } catch (e) {
      setError(e instanceof APIError ? e : new APIError(503));
    } finally {
      setBusy(false);
    }
  }
  const evidence = result?.response.evidence;
  return (
    <>
      <Heading
        title="Scout"
        subtitle="Ask away. Find the insight."
      />
      <div className="analyst-layout scout-layout">
        <div>
          <Tile className="composer">
            <Select id="scout-scope" labelText="Investigation scope" value={investigation ? "incidents" : "analytics"}
              disabled={busy} onChange={event => onScopeChange?.(event.target.value === "incidents")}>
              <SelectItem value="analytics" text="Infrastructure analytics" />
              <SelectItem value="incidents" text="Recorded SRE incidents" />
            </Select>
            {investigation && <>
              <p className="support sre-space">Read-only sandbox investigation of a controlled application-dependency HTTP 503 exercise, not a storage outage. No new probes or recovery actions run.</p>
              <TextInput id="scout-incident" labelText="Incident ID (optional for listing)" value={selectedId}
                invalid={invalidId} invalidText="Enter a valid incident UUID." disabled={busy}
                onChange={event => setSelectedId(event.target.value)} />
            </>}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void analyze();
              }}
            >
              <TextArea
                id="question"
                labelText="Ask Scout"
                hideLabel
                placeholder="What would you like to know about your infrastructure?"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={2000}
                rows={4}
                disabled={busy || contextLoading}
              />
              <div className="composer-actions">
                <Button
                  type="submit"
                  renderIcon={ArrowRight}
                  disabled={!question.trim() || busy || contextLoading || invalidId}
                >
                  Analyze
                </Button>
              </div>
            </form>
          </Tile>
          {busy && (
            <Tile className="analysis-progress">
              <InlineLoading description="Reviewing approved infrastructure evidence…" />
              <SkeletonText paragraph lineCount={3} />
            </Tile>
          )}
          {error && (
            <div className="result-notice">
              <Notice error={error} />
            </div>
          )}
          {result && evidence && (
            <Tile className="answer">
              <div className="panel-title">
                <div className="feature-label">
                  <CheckmarkOutline size={20} /> ANALYST ASSESSMENT
                </div>
                <Tag type="blue">{"analysis_scope" in result.context ? "Recorded incidents" : result.context.mode}</Tag>
              </div>
              <AnalystAnswer answer={result.response.answer} />
              {JSON.stringify(result.context) !== JSON.stringify(selectedContext) && (
                <p className="note">
                  This answer belongs to an earlier context. Submit again to
                  analyze the current selection.
                </p>
              )}
              <div className="provenance">
                <div className="section-label">TOOLS USED</div>
                <div>
                  {evidence.tools_used.map((tool) => (
                    <Tag key={tool} type="blue">
                      {tool}
                    </Tag>
                  ))}
                </div>
                <dl>
                  <div>
                    <dt>Reference time</dt>
                    <dd>{date(evidence.reference_time)}</dd>
                  </div>
                  {!("analysis_scope" in result.context) && <div>
                    <dt>Analysis window</dt>
                    <dd>
                      {date(evidence.window.start)} →{" "}
                      {date(evidence.window.end)}
                    </dd>
                  </div>}
                  <div>
                    <dt>Freshness</dt>
                    <dd>
                      {"analysis_scope" in result.context ? "Server assessment reference" : result.state} ·{" "}
                      {String(
                        evidence.freshness.threshold_seconds ?? "Not available",
                      )}
                      s threshold
                    </dd>
                  </div>
                  {evidence.currency !== null && <div>
                    <dt>Currency</dt>
                    <dd>{evidence.currency}</dd>
                  </div>}
                </dl>
                {"analysis_scope" in result.context
                  ? <p className="support">This saved answer describes evidence at the server reference time. Observations age after 15 seconds; submit again to reassess stored evidence. Historical verified recovery does not establish current health.</p>
                  : <CoverageEvidence coverage={evidence.coverage} />}
              </div>
              <Accordion>
                <AccordionItem title="Evidence" open={false}>
                  <p className="support">
                    Approved tool results and technical provenance. Values are recorded evidence, not new measurements.
                  </p>
                  {evidence.tool_results.map((t, i) => (
                    <div className="tool-detail" key={t.tool + i}>
                      <h3>{t.tool}</h3>
                      <p>
                        {t.returned_rows} returned rows ·{" "}
                        {t.warnings.join(" · ")}
                      </p>
                      <pre>{JSON.stringify(t, null, 2)}</pre>
                    </div>
                  ))}
                  <small>Request reference: {result.response.request_id}</small>
                </AccordionItem>
              </Accordion>
            </Tile>
          )}
        </div>
        <aside className="suggestions">
          <div className="section-label">TRY ASKING</div>
          <p className="support">Pick a question to get started.</p>
          {suggestions.map((q, i) => (
            <button
              key={q}
              className="suggestion"
              disabled={busy || contextLoading}
              onClick={() => setQuestion(q)}
            >
              <span className="suggestion-index">0{i + 1}</span>
              <span>{q}</span>
              <ArrowRight size={16} />
            </button>
          ))}
        </aside>
      </div>
    </>
  );
}
function Pipeline({ runs }: { runs: Run[] }) {
  const latest = runs[0];
  return (
    <>
      <Heading
        title="Data Pipeline"
        subtitle="Telemetry ingestion, transformation & analytics readiness"
      />
      <DemoETLAction />
      <Tile className="architecture">
        <div className="section-label">BACKEND DATA PATH · ARCHITECTURE</div>
        <div className="pipeline-path">
          {[
            "Telemetry source",
            "Raw preservation",
            "Validation",
            "Transformation",
            "PostgreSQL analytics",
            "FastAPI / AI",
          ].map((label, i) => (
            <div key={label}>
              <span>0{i + 1}</span>
              <b>{label}</b>
              {i < 5 && <ArrowRight size={16} />}
            </div>
          ))}
        </div>
        <p className="support">
          Architecture stages describe the system; live stage-level status is
          not exposed by the API.
        </p>
      </Tile>
      <DatabaseSample />
      {latest ? (
        <>
          <Tile className="latest-run">
            <div className="panel-title">
              <h2>Latest ingestion cycle</h2>
              <Tag
                type={
                  latest.status === "SUCCEEDED"
                    ? "green"
                    : latest.status === "FAILED"
                      ? "red"
                      : "cool-gray"
                }
              >
                {latest.status}
              </Tag>
            </div>
            <p className="support">
              {latest.source_id} · {latest.run_id}
            </p>
            <div className="run-counts">
              {[
                ["Extracted", latest.records_extracted],
                ["Accepted", latest.records_accepted],
                ["Inserted", latest.records_inserted],
                ["Duplicates", latest.records_duplicated],
                ["Rejected", latest.records_rejected],
              ].map(([label, count]) => (
                <div key={label}>
                  <small>{label}</small>
                  <strong>{count}</strong>
                </div>
              ))}
            </div>
            <div className="fact-list">
              <div>
                <span>Started</span>
                <b>{date(latest.started_at)}</b>
              </div>
              <div>
                <span>Finished</span>
                <b>{date(latest.finished_at)}</b>
              </div>
              <div>
                <span>Committed watermark</span>
                <b>{date(latest.watermark_after)}</b>
              </div>
            </div>
          </Tile>
          <Tile className="panel run-history">
            <div className="panel-title">
              <h2>Recent run history</h2>
              <span className="support">
                Latest {runs.length} · read-only audit
              </span>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    {[
                      "Run",
                      "Status",
                      "Extracted",
                      "Accepted",
                      "Inserted",
                      "Duplicates",
                      "Rejected",
                      "Started (CST)",
                    ].map((h) => (
                      <th key={h}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.run_id}>
                      <td title={r.run_id}>{r.run_id.slice(0, 8)}</td>
                      <td>
                        <Tag
                          size="sm"
                          type={
                            r.status === "SUCCEEDED"
                              ? "green"
                              : r.status === "FAILED"
                                ? "red"
                                : "cool-gray"
                          }
                        >
                          {r.status}
                        </Tag>
                      </td>
                      <td>{r.records_extracted}</td>
                      <td>{r.records_accepted}</td>
                      <td>{r.records_inserted}</td>
                      <td>{r.records_duplicated}</td>
                      <td>{r.records_rejected}</td>
                      <td>{date(r.started_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Tile>
        </>
      ) : (
        <Tile className="empty">No ETL audit runs exist for this source.</Tile>
      )}
    </>
  );
}
export default function App() {
  const [client] = useState(() => new APIClient());
  const [route, setRoute] = useState<AppRoute>(currentRoute);
  const page = route.page;
  const srePage = page === "Live Operations" || page === "Incident Center";
  const incidentScout = page === "AI Analyst" && !!route.investigation;
  const storedPage = srePage || incidentScout;
  const [sreBusy, setSREBusy] = useState(false);
  const [context, setContext] = useState(live);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [data, setData] = useState<Overview | null>(null);
  const [regions, setRegions] = useState<Region[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [updated, setUpdated] = useState<string | null>(null);
  const generation = useRef(0);
  function navigate(next: Page, incidentId?: string) {
    const hash = incidentId ? "#/incidents/" + encodeURIComponent(incidentId) : pageHashes[next];
    if (window.location.hash !== hash) window.history.pushState(null, "", hash);
    setRoute({ page: next, incidentId });
    setRefreshVersion(value => value + 1);
  }
  useEffect(() => {
    const update = () => setRoute(currentRoute());
    window.addEventListener("hashchange", update);
    window.addEventListener("popstate", update);
    return () => { window.removeEventListener("hashchange", update); window.removeEventListener("popstate", update); };
  }, []);
  useEffect(() => {
    document.querySelector<HTMLElement>(".sre-page-heading h1")?.focus();
  }, [route.page, route.incidentId]);
  useEffect(() => {
    const id = ++generation.current;
    setBusy(true);
    setError(null);
    setData(null);
    setRegions([]);
    setRuns([]);
    if (storedPage) {
      setBusy(false);
      return () => { generation.current++; };
    }
    const task = (async () => {
      const latest = await client.latestSuccessfulRun("simulated-cloud");
      const selected = contextForRun(latest);
      if (id !== generation.current) return;
      setContext(selected);
      if (page === "Overview") {
        const [o, r] = await Promise.all([client.overview(selected), client.regions(selected)]);
        if (id === generation.current) { setData(o.data); setRegions(r.data); }
      } else if (page === "Pipeline") {
        const result = await client.runs(selected);
        if (id === generation.current) setRuns(result.data);
      } else {
        const result = await client.overview(selected);
        if (id === generation.current) setData(result.data);
      }
    })();
    task
      .then(() => {
        if (id === generation.current) {
          setUpdated(new Date().toISOString());
        }
      })
      .catch((e) => {
        if (id === generation.current) {
          setError(e instanceof APIError ? e : new APIError(503));
        }
      })
      .finally(() => {
        if (id === generation.current) setBusy(false);
      });
    return () => {
      generation.current++;
    };
  }, [client, page, incidentScout, refreshVersion]);
  return (
    <div className="app-shell">
      <AppHeader
        page={page} referenceTime={context.reference_time} busy={srePage ? sreBusy : busy} storedEvidence={incidentScout}
        onNavigate={next => navigate(next)}
        onRefresh={() => setRefreshVersion(v => v + 1)}
      />
      <main>
        <div className="workspace">
          {!storedPage && error && <Notice error={error} />}{" "}
          {!storedPage && busy && (
            <div className="loading-panel">
              <InlineLoading description="Loading infrastructure analytics…" />
              <SkeletonText paragraph lineCount={5} />
            </div>
          )}
          {page === "Live Operations" && <LiveOperations client={client} refresh={refreshVersion} onRefresh={() => setRefreshVersion(value => value + 1)} onSelect={id => navigate("Incident Center", id)} onBusy={setSREBusy} />}
          {page === "Incident Center" && (route.incidentId
            ? <IncidentDetails key={route.incidentId} id={route.incidentId} client={client} refresh={refreshVersion} onRefresh={() => setRefreshVersion(value => value + 1)} onBack={() => navigate("Incident Center")} onBusy={setSREBusy} />
            : <IncidentCenter client={client} refresh={refreshVersion} onRefresh={() => setRefreshVersion(value => value + 1)} onSelect={id => navigate("Incident Center", id)} onBusy={setSREBusy} />)}
          {!busy && !error && page === "Overview" && data && (
            <OverviewView data={data} regions={regions} context={context} client={client} />
          )}
          {!busy && !error && page === "Pipeline" && <Pipeline runs={runs} />}
          {page === "AI Analyst" && (
            <AIAnalyst
              key={String(incidentScout) + (route.incidentId ?? "")}
              client={client}
              context={context}
              state={data ? telemetryState(data) : "NOT ASSESSED"}
              contextLoading={incidentScout ? false : busy}
              investigation={incidentScout}
              incidentId={route.incidentId}
              onScopeChange={incidents => {
                const hash = incidents ? "#/scout/incidents" : "#/scout";
                window.history.pushState(null, "", hash);
                setRoute({ page: "AI Analyst", investigation: incidents });
              }}
            />
          )}
          {!srePage && data && page !== "AI Analyst" && (
            <div className="workspace-footer">
              <span>
                Telemetry: {date(data.latest_telemetry_timestamp)} ·{" "}
                {telemetryState(data)}
              </span>
              <span>Last retrieved: {date(updated)}</span>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
