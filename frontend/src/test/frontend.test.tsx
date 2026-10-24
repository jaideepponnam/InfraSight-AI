import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Theme } from "@carbon/react";
import {
  APIClient,
  APIError,
  aiBody,
  query,
  RATE_LIMIT_MESSAGE,
  resolveAPIBase,
  snapshot,
  live,
  contextForRun,
} from "../api";
import { AIAnalyst, SUGGESTIONS } from "../App";
import { date, money, percent, telemetryState } from "../format";
import type { Overview, Run } from "../types";
afterEach(() => vi.unstubAllGlobals());
describe("HTTP client", () => {
  it("uses configured production API origin and preserves the local proxy", () => {
    expect(resolveAPIBase("https://api.jaideepponnam.com", true)).toBe(
      "https://api.jaideepponnam.com",
    );
    expect(resolveAPIBase("http://127.0.0.1:8001", false)).toBe("");
  });
  it.each([
    "http://remote.example",
    "https://user:secret@api.example",
    "https://api.example/path",
    "https://api.example?key=secret",
  ])("rejects unsafe production origin %s", (raw) => {
    expect(() => resolveAPIBase(raw, true)).toThrow();
  });
  it("sends production requests directly to the configured API", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ data: {}, meta: {} })));
    vi.stubGlobal("fetch", fetcher);
    await new APIClient(
      "public-demo-read",
      "https://api.jaideepponnam.com",
    ).overview(snapshot());
    expect(fetcher.mock.calls[0][0]).toMatch(
      /^https:\/\/api.jaideepponnam.com\/api\/v1\/analytics\/overview\?/,
    );
  });
  it("sends only read authorization with structural snapshot context", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ answer: "Test", evidence: {} })),
      );
    vi.stubGlobal("fetch", fetcher);
    await new APIClient("test-read-key").ask("Question", snapshot());
    const [url, options] = fetcher.mock.calls[0];
    expect(url).toBe("/api/v1/ai/query");
    expect(options.headers).toEqual({
      "X-API-Key": "test-read-key",
      "Content-Type": "application/json",
    });
    expect(JSON.parse(options.body)).toEqual(aiBody("Question", snapshot()));
    expect(JSON.parse(options.body)).not.toHaveProperty("mode");
    expect(JSON.parse(options.body).reference_time).toBe(
      "2026-10-11T19:33:00Z",
    );
  });
  it.each([401, 422, 429, 502, 503])(
    "sanitizes HTTP %s without retries",
    async (status) => {
      const fetcher = vi.fn().mockResolvedValue(
        new Response("provider-secret-detail", {
          status,
          headers: { "X-Request-ID": "ref" },
        }),
      );
      vi.stubGlobal("fetch", fetcher);
      await expect(
        new APIClient().ask("Question", snapshot()),
      ).rejects.toMatchObject({ status, requestId: "ref" });
      expect(fetcher).toHaveBeenCalledTimes(1);
    },
  );
  it("sanitizes transport errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("internal-secret")),
    );
    await expect(new APIClient().overview(snapshot())).rejects.toThrow(
      "analytics service is temporarily unavailable",
    );
  });
  it("rejects malformed envelopes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}")));
    await expect(new APIClient().overview(snapshot())).rejects.toMatchObject({
      status: 502,
    });
  });
  it("preserves analytics query boundaries", () => {
    const p = new URLSearchParams(query(snapshot()));
    expect(p.get("start")).toBe("2026-10-11T19:30:00Z");
    expect(p.get("as_of")).toBe(snapshot().reference_time);
    expect(p.get("min_samples")).toBeNull();
  });
});
describe("presentation integrity", () => {
  it("pins the displayed assessment to the completed run instead of the wall clock", () => {
    const run = { status: "SUCCEEDED", source_id: "simulated-cloud", requested_window_end: "2026-10-12T09:00:00Z" } as Run;
    const selected = contextForRun(run);
    expect(selected.reference_time).toBe("2026-10-12T09:00:00.000Z");
    expect(selected.end).toBe(selected.reference_time);
    expect(selected.start).toBe("2026-10-12T08:00:00.000Z");
    expect(selected.freshness_seconds).toBe(120);
    expect(contextForRun(run).reference_time).toBe(selected.reference_time);
    expect(contextForRun({ ...run, requested_window_end: "2026-10-12T09:02:00Z" }).reference_time).toBe("2026-10-12T09:02:00.000Z");
    expect(() => contextForRun({...run, status:"RUNNING"})).toThrow();
  });
  it("sends current Live context and keeps Snapshot historical", () => {
    const now = Date.now();
    const scope = live();
    expect(Math.abs(Date.parse(scope.reference_time) - now)).toBeLessThan(1000);
    expect(aiBody("Fleet health", scope).reference_time).toBe(scope.reference_time);
    expect(snapshot().reference_time).toBe("2026-10-11T19:33:00Z");
  });
  it("uses fixed CST for presentation without changing UTC request inputs", () => {
    expect(date("2026-10-11T19:33:00Z")).toBe("Oct 11, 2026, 1:33:00 PM CST");
    expect(date("2026-01-11T19:33:00Z")).toBe("Jan 11, 2026, 1:33:00 PM CST");
    expect(date(null)).toBe("Not available");
    expect(date("invalid")).toBe("Not available");
    expect(snapshot().reference_time).toBe("2026-10-11T19:33:00Z");
  });
  it("retains exact decimal money without binary floating point", () =>
    expect(money("12345678901234567890.12345678", "USD")).toBe(
      "USD 12345678901234567890.12345678",
    ));
  it("labels unknown and fraction percentages correctly", () => {
    expect(percent(null)).toBe("Not available");
    expect(percent("0.991", true)).toBe("99.1%");
    expect(money("NaN", "USD")).toBe("Not available");
  });
  it("preserves stale and no-data states", () => {
    expect(
      telemetryState({
        inventory_servers: 75,
        no_data_servers: 0,
        stale_servers: 75,
        healthy_servers: 0,
        warning_servers: 0,
        critical_servers: 0,
      } as Overview),
    ).toBe("STALE");
    expect(
      telemetryState({
        inventory_servers: 75,
        no_data_servers: 75,
      } as Overview),
    ).toBe("NO_DATA");
  });
});
describe("AI analyst", () => {
  const mount = (client: APIClient) =>
    render(
      <Theme theme="g100">
        <AIAnalyst client={client} context={snapshot()} state="FRESH" />
      </Theme>,
    );
  it("suggestion populates composer without submitting", async () => {
    const client = new APIClient();
    const ask = vi.spyOn(client, "ask");
    mount(client);
    await userEvent.click(
      screen.getByRole("button", {
        name: new RegExp(SUGGESTIONS[1].replace("?", "\?")),
      }),
    );
    expect(screen.getByLabelText("Ask Scout")).toHaveValue(
      SUGGESTIONS[1],
    );
    expect(ask).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Scout" })).toBeInTheDocument();
    expect(screen.getByText("Ask away. Find the insight.")).toBeInTheDocument();
    expect(screen.queryByText("ANALYSIS CONTEXT")).not.toBeInTheDocument();
    expect(screen.queryByText("APPROVED ANALYTICS TOOLS")).not.toBeInTheDocument();
    expect(screen.queryByText("Read-only")).not.toBeInTheDocument();
    expect(screen.queryByText(/Source, selected window/)).not.toBeInTheDocument();
  });
  it("shows calm 429 notification after explicit action only", async () => {
    const client = new APIClient();
    const ask = vi.spyOn(client, "ask").mockRejectedValue(new APIError(429));
    mount(client);
    await userEvent.type(
      screen.getByLabelText("Ask Scout"),
      "Fleet health",
    );
    await userEvent.click(screen.getByRole("button", { name: "Analyze" }));
    await waitFor(() =>
      expect(screen.getByText(RATE_LIMIT_MESSAGE)).toBeInTheDocument(),
    );
    expect(ask).toHaveBeenCalledTimes(1);
    expect(ask).toHaveBeenCalledWith("Fleet health", snapshot());
  });
  it("renders answer, exact currency and collapsed evidence", async () => {
    const client = new APIClient();
    vi.spyOn(client, "ask").mockResolvedValue({
      answer: "## Infrastructure assessment\n\n**Health:** STALE\n\n- Review freshness before acting.",
      request_id: "test",
      evidence: {
        tools_used: ["get_overview"],
        reference_time: snapshot().reference_time,
        window: { start: snapshot().start, end: snapshot().end },
        freshness: { threshold_seconds: 120 },
        coverage: [
          {
            kind: "period_cost",
            coverage_fraction: "0.993",
            cost_coverage_fraction: "0.993",
          },
        ],
        currency: "USD",
        tool_results: [],
      },
    });
    mount(client);
    await userEvent.type(
      screen.getByLabelText("Ask Scout"),
      "Overview",
    );
    await userEvent.click(screen.getByRole("button", { name: "Analyze" }));
    await screen.findByRole("heading", { name: "Infrastructure assessment" });
    expect(screen.getByText("Health:")).toBeInTheDocument();
    expect(screen.getByText("Review freshness before acting.")).toBeInTheDocument();
    expect(screen.getByText("get_overview")).toBeInTheDocument();
    const coverage = within(screen.getByRole("region", { name: "Coverage backend evidence" }));
    expect(coverage.getByText("period_cost")).toBeInTheDocument();
    expect(coverage.getByText("Observation-time coverage").nextElementSibling).toHaveTextContent("99.3%");
    expect(coverage.getByText("Priced observation-time coverage").nextElementSibling).toHaveTextContent("99.3%");
    expect(screen.getByRole("button", { name: "Evidence" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });
});


it("does not allow an AI request before the latest-run context finishes loading", async () => {
  const client = new APIClient();
  const ask = vi.spyOn(client, "ask");
  render(<AIAnalyst client={client} context={snapshot()} state="NOT ASSESSED" contextLoading />);
  expect(screen.getByLabelText("Ask Scout")).toBeDisabled();
  const submit = screen.getByRole("button", { name: "Analyze" });
  expect(submit).toBeDisabled();
  await userEvent.click(submit);
  expect(ask).not.toHaveBeenCalled();
});
