import { useEffect, useRef, useState } from "react";
import {
  Accordion,
  AccordionItem,
  Button,
  InlineLoading,
  InlineNotification,
  SkeletonText,
  Tag,
  TextArea,
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
import { date, money, numeric, percent, telemetryState } from "./format";
import type { AIResponse, Context, Overview, Region, Run } from "./types";

export const SUGGESTIONS = [
  "How is our infrastructure doing?",
  "Which servers are expensive but underutilized?",
  "Which region has the most critical infrastructure?",
  "Which servers exceeded 80% CPU?",
  "Did infrastructure cost increase versus the previous period?",
];
type Page = HeaderPage;
function Notice({ error }: { error: APIError }) {
  return (
    <InlineNotification
      kind={error.status === 429 ? "warning" : "error"}
      title={error.status === 429 ? "Analysis paused" : "Request unavailable"}
      subtitle={error.message}
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
}: {
  client: APIClient;
  context: Context;
  state: string;
  contextLoading?: boolean;
}) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<APIError | null>(null);
  const [result, setResult] = useState<{
    response: AIResponse;
    context: Context;
    state: string;
  } | null>(null);
  async function analyze() {
    if (!question.trim() || busy || contextLoading) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult({
        response: await client.ask(question, context),
        context: { ...context },
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
                  disabled={!question.trim() || busy || contextLoading}
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
                <Tag type="blue">{result.context.mode}</Tag>
              </div>
              <AnalystAnswer answer={result.response.answer} />
              {JSON.stringify(result.context) !== JSON.stringify(context) && (
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
                  <div>
                    <dt>Analysis window</dt>
                    <dd>
                      {date(evidence.window.start)} →{" "}
                      {date(evidence.window.end)}
                    </dd>
                  </div>
                  <div>
                    <dt>Freshness</dt>
                    <dd>
                      {result.state} ·{" "}
                      {String(
                        evidence.freshness.threshold_seconds ?? "Not available",
                      )}
                      s threshold
                    </dd>
                  </div>
                  <div>
                    <dt>Currency</dt>
                    <dd>{evidence.currency}</dd>
                  </div>
                </dl>
                <div className="section-label">COVERAGE · BACKEND EVIDENCE</div>
                {evidence.coverage.length ? (
                  evidence.coverage.slice(0, 4).map((c, i) => (
                    <div className="coverage-evidence" key={i}>
                      {Object.entries(c).map(([k, v]) => (
                        <span key={k}>
                          <b>{k.replaceAll("_", " ")}</b>:{" "}
                          {k.endsWith("fraction")
                            ? percent(v, true)
                            : String(v ?? "Not available")}
                        </span>
                      ))}
                    </div>
                  ))
                ) : (
                  <p className="support">
                    Coverage was not supplied by the selected tools.
                  </p>
                )}
              </div>
              <Accordion>
                <AccordionItem title="Evidence" open={false}>
                  <p className="support">
                    Approved tool results and technical provenance. Monetary
                    values remain exact strings.
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
          {SUGGESTIONS.map((q, i) => (
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
function Pipeline({ runs, client, onRefresh }: { runs: Run[]; client: APIClient; onRefresh: () => Promise<void> }) {
  const latest = runs[0];
  return (
    <>
      <Heading
        title="Data Pipeline"
        subtitle="Telemetry ingestion, transformation & analytics readiness"
      />
      <DemoETLAction client={client} onRefresh={onRefresh} />
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
  const [page, setPage] = useState<Page>("Overview");
  const [context, setContext] = useState(live);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [data, setData] = useState<Overview | null>(null);
  const [regions, setRegions] = useState<Region[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [updated, setUpdated] = useState<string | null>(null);
  const generation = useRef(0);
  useEffect(() => {
    const id = ++generation.current;
    setBusy(true);
    setError(null);
    setData(null);
    setRegions([]);
    setRuns([]);
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
  }, [client, page, refreshVersion]);
  return (
    <div className="app-shell">
      <AppHeader
        page={page} referenceTime={context.reference_time} busy={busy}
        onNavigate={next => { setPage(next); setRefreshVersion(v => v + 1); }}
        onRefresh={() => setRefreshVersion(v => v + 1)}
      />
      <main>
        <div className="workspace">
          {error && <Notice error={error} />}{" "}
          {busy && (
            <div className="loading-panel">
              <InlineLoading description="Loading infrastructure analytics…" />
              <SkeletonText paragraph lineCount={5} />
            </div>
          )}
          {!busy && !error && page === "Overview" && data && (
            <OverviewView data={data} regions={regions} context={context} client={client} />
          )}
          {!busy && !error && page === "Pipeline" && <Pipeline runs={runs} client={client} onRefresh={async () => {
              const id = generation.current;
              const [result, latest] = await Promise.all([client.runs(context), client.latestSuccessfulRun(context.source_id)]);
              if (id === generation.current) { setRuns(result.data); setContext(contextForRun(latest)); }
            }} />}
          {page === "AI Analyst" && (
            <AIAnalyst
              client={client}
              context={context}
              state={data ? telemetryState(data) : "NOT ASSESSED"}
              contextLoading={busy}
            />
          )}
          {data && page !== "AI Analyst" && (
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
