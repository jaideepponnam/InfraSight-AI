import type {
  AIResponse,
  Context,
  Envelope,
  Overview,
  Region,
  Run,
} from "./types";
export const RATE_LIMIT_MESSAGE =
  "AI analysis is temporarily rate limited. Existing infrastructure analytics remain available. Please retry shortly.";
export class APIError extends Error {
  constructor(
    public status: number,
    public requestId?: string,
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
export class APIClient {
  constructor(private key = import.meta.env.VITE_API_READ_KEY || "") {}
  async request<T>(path: string, body?: unknown): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), body ? 70000 : 15000);
    try {
      const response = await fetch("/api/v1/" + path, {
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
      if (!response.ok)
        throw new APIError(
          response.status,
          response.headers.get("X-Request-ID") || undefined,
        );
      const data: unknown = await response.json();
      if (
        !data ||
        typeof data !== "object" ||
        (body
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
  runs(context: Context) {
    return this.request<Envelope<Run[]>>(
      "etl/runs?" +
        new URLSearchParams({ source_id: context.source_id, limit: "8" }),
    );
  }
  ask(question: string, context: Context) {
    return this.request<AIResponse>("ai/query", aiBody(question, context));
  }
}
