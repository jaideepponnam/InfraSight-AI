import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import App from "../App";
import { DemoETLAction } from "../DemoETLAction";
import type { Run } from "../types";

const explanation = "Telemetry ingestion is managed by an operator. This page displays recorded runs. Refresh to view new results.";

afterEach(() => vi.unstubAllGlobals());

it("explains operator-managed ingestion without executing requests or offering a run control", () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  render(<DemoETLAction />);
  expect(screen.getByText(explanation)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Run Demo ETL/i })).not.toBeInTheDocument();
  expect(fetcher).not.toHaveBeenCalled();
});

it.each([false, true])("keeps Pipeline history and refresh read-only (existing history: %s)", async populated => {
  let refreshed = false;
  const run = (id: string): Run => ({
    run_id: id, source_id: "simulated-cloud", status: "SUCCEEDED",
    requested_window_start: "2026-10-30T09:00:00Z", requested_window_end: "2026-10-30T09:02:00Z",
    started_at: "2026-10-30T09:02:00Z", finished_at: "2026-10-30T09:02:01Z",
    records_extracted: 300, records_accepted: 297, records_inserted: 297,
    records_duplicated: 0, records_rejected: 3, watermark_after: "2026-10-30T09:02:00Z",
  });
  const fetcher = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname !== "/api/v1/etl/runs" || (options?.method ?? "GET") !== "GET") {
      throw new Error("Unexpected request from read-only Pipeline");
    }
    const rows = refreshed ? [run("operator-run-2")] : populated ? [run("operator-run-1")] : [];
    return new Response(JSON.stringify({ data: rows, meta: { request_id: "test" } }));
  });
  vi.stubGlobal("fetch", fetcher);
  window.history.replaceState(null, "", "#/pipeline");
  render(<App />);

  await screen.findByText(explanation);
  if (populated) {
    expect(screen.getByText(/operator-run-1/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Recent run history" })).toBeInTheDocument();
  } else {
    expect(screen.getByText("No ETL audit runs exist for this source.")).toBeInTheDocument();
  }
  expect(screen.queryByRole("button", { name: /Run Demo ETL/i })).not.toBeInTheDocument();

  const beforeRefresh = fetcher.mock.calls.length;
  refreshed = true;
  await userEvent.click(screen.getByRole("button", { name: "Refresh analytics" }));
  await screen.findByText(/operator-run-2/);
  await waitFor(() => expect(fetcher.mock.calls.length).toBeGreaterThan(beforeRefresh));
  expect(screen.getByText(explanation)).toBeInTheDocument();
  expect(screen.queryByText("No ETL audit runs exist for this source.")).not.toBeInTheDocument();

  for (const [url, options] of fetcher.mock.calls) {
    expect(String(url)).not.toContain("/demo/etl/run");
    expect(options?.method).toBe("GET");
    expect(options?.headers).not.toHaveProperty("X-Admin-Key");
  }
});
