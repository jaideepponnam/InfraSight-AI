import type {
  AIResponse,
  AverageHealth,
  DemoETLResult,
  Context,
  Envelope,
  Overview,
  Region,
  Run,
} from "./types";
import { arrayOf, checked as validateSRE, isEvidence, isEvent, isIncident, isRun, isService, isUUID } from "./sre/contracts";
import type { IncidentState, SREEnvelope } from "./sre/types";
export const RATE_LIMIT_MESSAGE =
  "AI analysis is temporarily rate limited. Existing infrastructure analytics remain available. Please retry shortly.";
export class APIError extends Error {
  constructor(
    public status: number,
    public requestId?: string,
    public code?: "SRE_DISABLED",
  ) {
    super(
      (
        {
          401: "Read access could not be verified. Configure a valid read API key.",
          403: "This operation is not authorized.",
          422: "Check the question and selected analysis context.",
          429: RATE_LIMIT_MESSAGE,
          502: "AI analysis could not complete. No answer was generated.",
          503: "The analytics service is temporarily unavailable.",
          504: "The request took too long. Please retry when ready.",
        } as Record<number, string>
      )[status] || "The request could not complete. Please retry when ready.",
    );
  }
}
function checked<T>(value: unknown, validate: (v: unknown) => v is T): SREEnvelope<T> {
  try { return validateSRE(value, validate); }
  catch { throw new APIError(502); }
}
function resourceId(id: string): string {
  if (!isUUID(id)) throw new APIError(422);
  return encodeURIComponent(id.toLowerCase());
}
export function snapshot(): Context {
  return {
    mode: "SNAPSHOT",
    source_id: "simulated-cloud",
    reference_time: "2026-10-11T19:33:00Z",
    start: "2026-10-11T19:30:00Z",
    end: "2026-10-11T19:33:00Z",
    currency: "USD",
    freshness_seconds: 120,
    min_samples: 4,
  };
}
export function live(): Context {
  const now = new Date();
  return {
    ...snapshot(),
    mode: "LIVE",
    reference_time: now.toISOString(),
    start: new Date(now.getTime() - 3600000).toISOString(),
    end: now.toISOString(),
    min_samples: 20,
  };
}
export function contextForRun(run: Run | null): Context {
  const scope = live();
  if (!run) return scope;
  const end = Date.parse(run.requested_window_end || "");
  if (run.status !== "SUCCEEDED" || run.source_id !== scope.source_id || !Number.isFinite(end))
    throw new APIError(502);
  return { ...scope, reference_time: new Date(end).toISOString(),
    start: new Date(end - 3600000).toISOString(), end: new Date(end).toISOString() };
}

export function query(context: Context) {
  return new URLSearchParams({
    source_id: context.source_id,
    as_of: context.reference_time,
    start: context.start,
    end: context.end,
    currency: context.currency,
    freshness_seconds: String(context.freshness_seconds),
  }).toString();
}
export function aiBody(question: string, context: Context) {
  const { mode: _mode, ...scope } = context;
  return { question: question.trim(), ...scope };
}
export function resolveAPIBase(raw: string, production: boolean): string {
  if (!production) return ""; // Local Vite proxy preserves the development setup.
  const url = new URL(raw);
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (
    (url.protocol !== "https:" && !(local && url.protocol === "http:")) ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  )
    throw new Error(
      "Configure a valid API origin without credentials or paths.",
    );
  return url.origin;
}

export class APIClient {
  constructor(
    private key = import.meta.env.VITE_API_READ_KEY || "",
    private baseURL = resolveAPIBase(
      import.meta.env.VITE_API_BASE_URL || "",
      import.meta.env.PROD,
    ),
  ) {}
  async request<T>(path: string, body?: unknown, shape: "ai" | "envelope" = body ? "ai" : "envelope"): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), body ? 70000 : 15000);
    try {
      const response = await fetch(this.baseURL + "/api/v1/" + path, {
        method: body ? "POST" : "GET",
        headers: {
          "X-API-Key": this.key,
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
        signal: controller.signal,
        credentials: "omit",
        redirect: "error",
      });
      if (!response.ok) {
        let code: "SRE_DISABLED" | undefined;
        if (path.startsWith("sre/")) {
          try {
            const payload = await response.json();
            if (payload?.error?.code === "SRE_DISABLED") code = "SRE_DISABLED";
          } catch { /* Keep arbitrary backend error bodies out of the UI. */ }
        }
        throw new APIError(
          response.status,
          response.headers.get("X-Request-ID") || undefined,
          code,
        );
      }
      const data: unknown = await response.json();
      if (
        !data ||
        typeof data !== "object" ||
        (shape === "ai"
          ? !("answer" in data && "evidence" in data)
          : !("data" in data && "meta" in data))
      )
        throw new APIError(502);
      return data as T;
    } catch (error) {
      if (error instanceof APIError) throw error;
      throw new APIError(
        error instanceof DOMException && error.name === "AbortError"
          ? 504
          : 503,
      );
    } finally {
      clearTimeout(timer);
    }
  }
  averageHealth(context: Context) {
    return this.request<Envelope<AverageHealth[]>>("analytics/average-health?" + query(context));
  }
  // SRE is read-only in the browser. No admin header, token or mutation method.
  async sreServices() {
    return checked(await this.request<unknown>("sre/services"), arrayOf(isService));
  }
  async sreIncidents(params: { state?: IncidentState; limit?: number; offset?: number } = {}) {
    const query = new URLSearchParams({ limit: String(params.limit ?? 20), offset: String(params.offset ?? 0) });
    if (params.state) query.set("state", params.state);
    const result = checked(await this.request<unknown>("sre/incidents?" + query), arrayOf(isIncident));
    if (result.meta.total == null || result.meta.limit == null || result.meta.offset == null) throw new APIError(502);
    return result;
  }
  async sreIncident(id: string) {
    const result = checked(await this.request<unknown>("sre/incidents/" + resourceId(id)), isIncident);
    if (result.data.id !== id.toLowerCase()) throw new APIError(502);
    return result;
  }
  async sreEvents(id: string) {
    const result = checked(await this.request<unknown>("sre/incidents/" + resourceId(id) + "/events"), arrayOf(isEvent));
    if (result.data.some(event => event.incident_id !== id.toLowerCase())) throw new APIError(502);
    return result;
  }
  async sreEvidence(id: string) {
    const result = checked(await this.request<unknown>("sre/incidents/" + resourceId(id) + "/evidence"), isEvidence);
    if (result.data.recovery_attempts.some(attempt => attempt.incident_id !== id.toLowerCase())) throw new APIError(502);
    return result;
  }
  async sreRun(id: string) {
    const result = checked(await this.request<unknown>("sre/demo-runs/" + resourceId(id)), isRun);
    if (result.data.id !== id.toLowerCase()) throw new APIError(502);
    return result;
  }
  overview(context: Context) {
    return this.request<Envelope<Overview>>(
      "analytics/overview?" + query(context),
    );
  }
  regions(context: Context) {
    return this.request<Envelope<Region[]>>(
      "analytics/regions?" + query(context),
    );
  }
  async latestSuccessfulRun(sourceId: string): Promise<Run | null> {
    const response = await this.request<Envelope<Run[]>>("etl/runs?" + new URLSearchParams({ source_id: sourceId, status: "SUCCEEDED", limit: "1" }));
    return response.data[0] || null;
  }
  runs(context: Context) {
    return this.request<Envelope<Run[]>>(
      "etl/runs?" +
        new URLSearchParams({ source_id: context.source_id, limit: "8" }),
    );
  }
  demoETL() {
    return this.request<Envelope<DemoETLResult>>("demo/etl/run", {}, "envelope");
  }
  ask(question: string, context: Context) {
    return this.request<AIResponse>("ai/query", aiBody(question, context));
  }
}
