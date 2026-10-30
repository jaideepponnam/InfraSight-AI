import { useEffect, useRef, useState } from "react";
import { Button, InlineLoading, InlineNotification, Tag, Tile } from "@carbon/react";
import { APIClient, APIError } from "./api";
import { date } from "./format";
import type { DemoETLResult } from "./types";

function failureMessage(error: APIError): string {
  if (error.code === "DEMO_PUBLIC_ETL_DISABLED")
    return "Run ETL is not enabled for this demo. Existing run history is still available.";
  if (error.status === 409)
    return "Another simulated telemetry run is in progress. Try again after it finishes.";
  if (error.status === 401 || error.status === 403)
    return "Demo access could not be verified. Refresh the page or contact the demo owner.";
  if (error.status === 404)
    return "This backend does not provide the public ETL demo yet.";
  if (error.status === 422)
    return "The demo request was rejected. Refresh the page before trying again.";
  if (error.status === 504)
    return "The request timed out. The run may still complete. Refresh run history before starting another run.";
  return "The demo request could not complete. Refresh run history before trying again.";
}

export function DemoETLAction({ client, onRefresh }: {
  client: APIClient;
  onRefresh: () => Promise<void>;
}) {
  const pending = useRef(false);
  const mounted = useRef(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DemoETLResult | null>(null);
  const [error, setError] = useState<APIError | null>(null);
  const [refreshFailed, setRefreshFailed] = useState(false);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  async function run() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setResult(null);
    setError(null);
    setRefreshFailed(false);
    try {
      const response = await client.publicDemoETL();
      if (!mounted.current) return;
      setResult(response.data);
      try { await onRefresh(); }
      catch { if (mounted.current) setRefreshFailed(true); }
    } catch (failure) {
      if (mounted.current)
        setError(failure instanceof APIError ? failure : new APIError(503));
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <Tile className="demo-etl">
      <div className="panel-title">
        <div>
          <h2>Demo ingestion</h2>
          <p className="support">Generate and ingest a bounded window of simulated telemetry.</p>
        </div>
        <Button onClick={() => void run()} disabled={busy}>
          {busy ? "Running ETL" : "Run ETL"}
        </Button>
      </div>
      <p className="support">Results and recorded run history refresh after the cycle completes.</p>
      {busy && <InlineLoading description="Processing simulated telemetry..." />}
      {error && <InlineNotification kind="error" hideCloseButton title="ETL request unavailable" subtitle={failureMessage(error)} />}
      {result && (
        <div role="region" aria-label="ETL run result" aria-live="polite">
          <Tag type={result.status === "SUCCEEDED" ? "green" : "red"}>{result.status}</Tag>
          <p className="support">Run {result.run_id}</p>
          <p className="support">{date(result.window_start)} through {date(result.window_end)}</p>
          <div className="run-counts">
            {[
              ["Extracted", result.counts.extracted],
              ["Accepted", result.counts.accepted],
              ["Inserted", result.counts.inserted],
              ["Duplicated", result.counts.duplicated],
              ["Rejected", result.counts.rejected],
            ].map(([label, value]) => (
              <div key={label}><small>{label}</small><strong>{value}</strong></div>
            ))}
          </div>
          {result.status === "FAILED" && <InlineNotification kind="error" hideCloseButton title="ETL run failed" subtitle="The pipeline recorded a failed run. Its actual counters and audit history remain available." />}
        </div>
      )}
      {refreshFailed && <InlineNotification kind="warning" hideCloseButton title="History refresh unavailable" subtitle="The run result is shown above. Use Refresh analytics to reload the audit history." />}
    </Tile>
  );
}
