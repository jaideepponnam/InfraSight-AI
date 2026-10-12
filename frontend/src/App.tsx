import { useEffect, useRef, useState } from "react";
import {
  Accordion,
  AccordionItem,
  Button,
  InlineLoading,
  InlineNotification,
  Select,
  SelectItem,
  SkeletonText,
  Tag,
  TextArea,
  Tile,
} from "@carbon/react";
import {
  Analytics,
  Dashboard,
  DataConnected,
  Renew,
  ArrowRight,
  CheckmarkOutline,
  Information,
} from "@carbon/icons-react";
import { APIClient, APIError, live, snapshot } from "./api";
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
const PAGES = ["Overview", "AI Analyst", "Pipeline"] as const;
type Page = (typeof PAGES)[number];
const icons = [Dashboard, Analytics, DataConnected];
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
      <div className="eyebrow">INFRASTRUCTURE INTELLIGENCE / WORKSPACE</div>
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
}: {
  data: Overview;
  regions: Region[];
  context: Context;
}) {
  const states = [
    ["Healthy", data.healthy_servers, "healthy"],
    ["Warning", data.warning_servers, "warning"],
    ["Critical", data.critical_servers, "critical"],
    ["Stale", data.stale_servers, "stale"],
    ["No data", data.no_data_servers, "no-data"],
  ] as const;
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
        <Tile className="panel">
          <div className="panel-title">
            <h2>Infrastructure health</h2>
            <Tag type="cool-gray">{telemetryState(data)}</Tag>
          </div>
          <p className="support">
            Effective health at the selected reference, including stale and
            missing telemetry.
          </p>
          <div
            className="health-strip"
            role="img"
            aria-label={states
              .map(([label, count]) => label + ": " + count)
              .join(", ")}
          >
            {states
              .filter(([, count]) => count > 0)
              .map(([label, count, tone]) => (
                <span
                  key={label}
                  className={tone}
                  style={{ flex: count }}
                  title={label + ": " + count}
                />
              ))}
          </div>
          <div className="health-legend">
            {states.map(([label, count, tone]) => (
              <div key={label}>
                <i className={tone} />
                <span>{label}</span>
                <b>{count}</b>
              </div>
            ))}
          </div>
          <div className="section-label">REGIONAL FLEET</div>
          {regions.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Region / source</th>
                    <th>Healthy</th>
                    <th>Warning</th>
                    <th>Critical</th>
                    <th>Stale / no data</th>
                  </tr>
                </thead>
                <tbody>
                  {regions.map((r) => (
                    <tr key={r.source_id + r.region_code}>
                      <td>
                        <b>{r.region_code}</b>
                        <small>{r.source_id}</small>
                      </td>
                      <td className="healthy">{r.healthy_servers}</td>
                      <td className="warning">{r.warning_servers}</td>
                      <td className="critical">{r.critical_servers}</td>
                      <td>
                        {r.stale_servers} / {r.no_data_servers}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty">No regional observations in this context.</p>
          )}
        </Tile>
        <Tile className="panel">
          <div className="panel-title">
            <h2>Resource intelligence</h2>
            <Tag type="blue">Utilization</Tag>
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
}: {
  client: APIClient;
  context: Context;
  state: string;
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
    if (!question.trim() || busy) return;
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
        title="AI Analyst"
        subtitle="Evidence-grounded infrastructure intelligence"
      />
      <div className="analyst-layout">
        <div>
          <Tile className="composer">
            <div className="panel-title">
              <div className="feature-label">
                <Analytics size={20} /> APPROVED ANALYTICS TOOLS
              </div>
              <Tag type="blue">Read-only</Tag>
            </div>
            <h2>Turn infrastructure data into a clear answer.</h2>
            <p className="support">
              Ask about fleet health, resource pressure or observed cost.
              Answers use controlled backend tools and actual PostgreSQL
              analytics.
            </p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void analyze();
              }}
            >
              <TextArea
                id="question"
                labelText="Your investigation"
                placeholder="Which servers are expensive but underutilized?"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={2000}
                rows={4}
                disabled={busy}
              />
              <div className="composer-actions">
                <small>
                  Source, UTC window and currency travel with this request.
                </small>
                <Button
                  type="submit"
                  renderIcon={ArrowRight}
                  disabled={!question.trim() || busy}
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
                <Tag type="cyan">{result.context.mode}</Tag>
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
          <div className="section-label">SUGGESTED INVESTIGATIONS</div>
          <p className="support">Choose a starting point, then Analyze.</p>
          {SUGGESTIONS.map((q, i) => (
            <button
              key={q}
              className="suggestion"
              disabled={busy}
              onClick={() => setQuestion(q)}
            >
              <span className="suggestion-index">0{i + 1}</span>
              <span>{q}</span>
              <ArrowRight size={16} />
            </button>
          ))}
          <div className="scope-card">
            <div className="section-label">ANALYSIS CONTEXT</div>
            <Tag type="cyan">{context.mode}</Tag>
            <p>{context.source_id}</p>
            <small>
              {date(context.start)}
              <br />
              through {date(context.end)}
            </small>
            <div className="scope-footer">
              {context.currency} · {context.freshness_seconds}s freshness ·{" "}
              {context.min_samples} minimum samples
            </div>
          </div>
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
                      "Started (UTC)",
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
  const [context, setContext] = useState(snapshot);
  const [data, setData] = useState<Overview | null>(null);
  const [regions, setRegions] = useState<Region[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [connected, setConnected] = useState(false);
  const [updated, setUpdated] = useState<string | null>(null);
  const generation = useRef(0);
  useEffect(() => {
    const id = ++generation.current;
    setBusy(true);
    setError(null);
    setData(null);
    setRegions([]);
    setRuns([]);
    const task =
      page === "Overview"
        ? Promise.all([client.overview(context), client.regions(context)]).then(
            ([o, r]) => {
              if (id === generation.current) {
                setData(o.data);
                setRegions(r.data);
              }
            },
          )
        : page === "Pipeline"
          ? client.runs(context).then((r) => {
              if (id === generation.current) setRuns(r.data);
            })
          : client.overview(context).then((o) => {
              if (id === generation.current) setData(o.data);
            });
    task
      .then(() => {
        if (id === generation.current) {
          setConnected(true);
          setUpdated(new Date().toISOString());
        }
      })
      .catch((e) => {
        if (id === generation.current) {
          setError(e instanceof APIError ? e : new APIError(503));
          setConnected(false);
        }
      })
      .finally(() => {
        if (id === generation.current) setBusy(false);
      });
    return () => {
      generation.current++;
    };
  }, [client, page, context]);
  return (
    <div className="app-shell">
      <aside className="navigation">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("Overview");
          }}
        >
          <span className="brand-mark">
            <DataConnected size={24} />
          </span>
          <span>
            InfraSight <b>AI</b>
            <small>Infrastructure Intelligence</small>
          </span>
        </a>
        <div className="nav-caption">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {PAGES.map((p, i) => {
            const Icon = icons[i];
            return (
              <button
                key={p}
                aria-current={page === p ? "page" : undefined}
                onClick={() => setPage(p)}
              >
                <Icon size={20} />
                <span>{p}</span>
              </button>
            );
          })}
        </nav>
        <div className="nav-footer">
          <span>CONTROLLED ANALYTICS</span>
          <small>
            Structured data.
            <br />
            Traceable answers.
          </small>
          <Tag type="cool-gray">UTC reporting</Tag>
        </div>
      </aside>
      <main>
        <header className="context-toolbar">
          <div className="context-source">
            <small>SOURCE</small>
            <b>{context.source_id}</b>
          </div>
          <Select
            id="mode"
            labelText="Reference mode"
            size="sm"
            value={context.mode}
            onChange={(e) =>
              setContext(e.target.value === "SNAPSHOT" ? snapshot() : live())
            }
          >
            <SelectItem value="SNAPSHOT" text="Snapshot demo" />
            <SelectItem value="LIVE" text="Live · last hour" />
          </Select>
          <div className="context-reference">
            <small>REFERENCE · UTC</small>
            <b>{date(context.reference_time)}</b>
          </div>
          <div className="toolbar-status">
            <Tag type="cyan">{context.mode}</Tag>
            <span className={"connection " + (connected ? "connected" : "")}>
              <i />
              {busy
                ? "Connecting"
                : connected
                  ? "API connected"
                  : "API unverified"}
            </span>
          </div>
          <Button
            hasIconOnly
            renderIcon={Renew}
            iconDescription="Refresh analytics"
            kind="ghost"
            size="sm"
            onClick={() =>
              setContext(context.mode === "LIVE" ? live() : { ...context })
            }
          />
        </header>
        <div className="workspace">
          {context.mode === "SNAPSHOT" && (
            <div className="snapshot-note">
              <Tag type="cyan" size="sm">
                SNAPSHOT
              </Tag>
              <span>
                Historical interview dataset · 11 Oct 2026, 19:30–19:33 UTC ·
                health evaluated at the selected reference.
              </span>
            </div>
          )}
          {error && <Notice error={error} />}{" "}
          {busy && (
            <div className="loading-panel">
              <InlineLoading description="Loading infrastructure analytics…" />
              <SkeletonText paragraph lineCount={5} />
            </div>
          )}
          {!busy && !error && page === "Overview" && data && (
            <OverviewView data={data} regions={regions} context={context} />
          )}
          {!busy && !error && page === "Pipeline" && <Pipeline runs={runs} />}
          {page === "AI Analyst" && (
            <AIAnalyst
              client={client}
              context={context}
              state={data ? telemetryState(data) : "NOT ASSESSED"}
            />
          )}
          {data && (
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
