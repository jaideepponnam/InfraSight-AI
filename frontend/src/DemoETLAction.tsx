import { useState } from "react";
import { Button, InlineLoading, InlineNotification, Tag, Tile } from "@carbon/react";
import { APIClient, APIError } from "./api";
import { date } from "./format";
import type { DemoETLResult } from "./types";

export function DemoETLAction({ client, onRefresh }: { client: APIClient; onRefresh: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DemoETLResult | null>(null);
  const [error, setError] = useState<APIError | null>(null);
  const [refreshFailed, setRefreshFailed] = useState(false);
  async function run() {
    setBusy(true); setResult(null); setError(null); setRefreshFailed(false);
    try {
      const response = await client.demoETL();
      setResult(response.data);
      try { await onRefresh(); } catch { setRefreshFailed(true); }
    } catch (e) { setError(e instanceof APIError ? e : new APIError(503)); }
    finally { setBusy(false); }
  }
  return <Tile className="demo-etl">
    <div className="panel-title">
      <div><h2>Demo ingestion</h2><p className="support">Generates and processes up to two minutes of simulated server telemetry.</p></div>
      <Button onClick={() => void run()} disabled={busy}>{busy ? "Running Demo ETL" : "Run Demo ETL"}</Button>
    </div>
    <p className="support">After ingestion, open Overview or Scout to view the latest telemetry.</p>
    {busy && <InlineLoading description="Processing telemetry..." />}
    {error && <InlineNotification kind="error" hideCloseButton title="Demo ETL unavailable" subtitle={
      error.status === 409 ? "A simulator cycle is already running. Please try again after it completes." :
      error.status === 401 || error.status === 403 ? "Demo access could not be verified." :
      error.status === 504 ? "The request timed out. Refresh run history before retrying; ingestion may still be completing." :
      "The demo cycle could not complete. Refresh run history or retry shortly."
    } />}
    {result && <div aria-live="polite">
      <Tag type={result.status === "SUCCEEDED" ? "green" : "red"}>{result.status}</Tag>
      <p className="support">{date(result.window_start)} through {date(result.window_end)}</p>
      <div className="run-counts">{Object.entries(result.counts).map(([key, value]) => <div key={key}><small>{key === "duplicated" ? "Duplicates" : key[0].toUpperCase() + key.slice(1)}</small><strong>{value}</strong></div>)}</div>
      {result.status === "FAILED" && <InlineNotification kind="error" hideCloseButton title="Demo ETL failed" subtitle="The pipeline recorded a failed run. Its counters and audit history remain available." />}
    </div>}
    {refreshFailed && <InlineNotification kind="warning" hideCloseButton title="History refresh unavailable" subtitle="The run result is shown above. Use Refresh analytics to reload the audit history." />}
  </Tile>;
}
