import { useEffect, useState, type DependencyList, type ReactNode } from "react";
import { Button, InlineLoading, InlineNotification, SkeletonText, Tag, Tile } from "@carbon/react";
import { APIError } from "../api";
import { date } from "../format";
import type { IncidentState } from "./types";

export function asAPIError(error: unknown): APIError {
  return error instanceof APIError ? error : new APIError(503);
}
export function useRead<T>(load: () => Promise<T>, dependencies: DependencyList) {
  const [state, setState] = useState<{ loading: boolean; data?: T; error?: APIError; retrieved?: string }>({ loading: true });
  useEffect(() => {
    let active = true;
    setState({ loading: true });
    load().then(data => {
      if (active) setState({ loading: false, data, retrieved: new Date().toISOString() });
    }).catch(error => {
      if (active) setState({ loading: false, error: asAPIError(error) });
    });
    return () => { active = false; };
    // Callers supply their resource identity and explicit refresh dependencies.
  }, dependencies);
  return state;
}
export function useNow() {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return now;
}
export function useBusy(loading: boolean, onBusy: (value: boolean) => void) {
  useEffect(() => { onBusy(loading); return () => onBusy(false); }, [loading, onBusy]);
}
export function SRETime({ value }: { value: string | null | undefined }) {
  return value ? <time dateTime={value} title={value}>{date(value)}</time> : <span>Not recorded</span>;
}
export function StateTag({ state }: { state: string }) {
  const normalized = state.toUpperCase();
  const type = ["HEALTHY", "RESOLVED", "VERIFIED"].includes(normalized) ? "green"
    : ["DEGRADED", "FAILED"].includes(normalized) ? "red"
    : ["STALE", "INTERRUPTED"].includes(normalized) ? "warm-gray" : "cool-gray";
  return <Tag type={type} size="sm">{state.replaceAll("_", " ")}</Tag>;
}
export function LifecycleTag({ state }: { state: IncidentState }) {
  return <StateTag state={state} />;
}
export function SREHeading({ title, children }: { title: string; children: ReactNode }) {
  return <div className="sre-page-heading page-heading"><div className="eyebrow">SRE OPERATIONS</div>
    <h1 tabIndex={-1}>{title}</h1><p>{children}</p></div>;
}
export function EvidenceBoundary() {
  return <div className="sre-boundary"><Tag type="blue" size="sm">On-demand evidence</Tag>
    <p>Controlled application-dependency exercises, not storage outages. Refresh reads stored records and does not run probes.</p></div>;
}
export function SREProblem({ error, title, onRetry }: { error: APIError; title?: string; onRetry?: () => void }) {
  const unauthorized = error.status === 401 || error.status === 403;
  const heading = title ?? (unauthorized ? "Read access unavailable" : error.code === "SRE_DISABLED" ? "Incident engine disabled" : error.status === 404 ? "Incident unavailable" : "SRE evidence unavailable");
  const message = unauthorized ? "This session is not authorized to read SRE records."
    : error.code === "SRE_DISABLED" ? "The incident engine is disabled on this backend. Existing analytics remain available."
    : error.status === 404 ? "This incident was not found. Return to Incident Center to select an available record."
    : error.status === 422 ? "This incident link or filter is invalid."
    : error.status === 502 ? "The response could not be validated. No health or recovery conclusion has been drawn."
    : error.status === 504 ? "Retrieval timed out. Refresh to try reading the evidence again."
    : "Stored SRE records could not be retrieved. No current health conclusion is available.";
  return <div className="sre-problem"><InlineNotification kind={unauthorized ? "warning" : "error"} title={heading} subtitle={message} hideCloseButton lowContrast />
    {error.requestId && <p className="support">Request reference: <code>{error.requestId}</code></p>}
    {onRetry && <Button kind="tertiary" size="sm" onClick={onRetry}>Retry retrieval</Button>}</div>;
}
export function SRELoading() {
  return <div className="loading-panel" role="status"><InlineLoading description="Retrieving SRE records..." /><SkeletonText paragraph lineCount={4} /></div>;
}
export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return <Tile className="sre-empty"><h2>{title}</h2><p>{children}</p></Tile>;
}
export function RetrievalTime({ value }: { value: string | undefined }) {
  return value ? <p className="sre-retrieved">Last retrieved <SRETime value={value} />. Observation times are shown separately.</p> : null;
}
export function unwrap<T>(result: PromiseSettledResult<T>): T | undefined {
  return result.status === "fulfilled" ? result.value : undefined;
}
export function failure(result: PromiseSettledResult<unknown>): APIError | undefined {
  return result.status === "rejected" ? asAPIError(result.reason) : undefined;
}
export function requireReadAuthorization(results: PromiseSettledResult<unknown>[]) {
  for (const result of results) {
    const error = failure(result);
    if (error?.status === 401 || error?.status === 403) throw error;
  }
}
