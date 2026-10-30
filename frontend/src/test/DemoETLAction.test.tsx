import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import App from "../App";
import { APIClient, APIError } from "../api";
import { DemoETLAction } from "../DemoETLAction";
import type { DemoETLResult, Envelope, Run } from "../types";

const publicPath = "/api/v1/demo/public-etl/run";
function result(id = "demo-run-1"): Envelope<DemoETLResult> {
  return { data: {
    run_id: id, source_id: "simulated-cloud", status: "SUCCEEDED",
    window_start: "2026-10-30T09:00:00Z", window_end: "2026-10-30T09:02:00Z",
    watermark_before: null, watermark_after: "2026-10-30T09:02:00Z",
    counts: { extracted: 14, accepted: 13, inserted: 7, duplicated: 6, rejected: 1 },
    error_code: null,
  }, meta: { request_id: "test" } };
}
const client = () => new APIClient("public-test", "");

function expectCounts(data: DemoETLResult) {
  const region = within(screen.getByRole("region", { name: "ETL run result" }));
  for (const [field, value] of Object.entries(data.counts)) {
    const label = field[0].toUpperCase() + field.slice(1);
    expect(within(region.getByText(label).parentElement!).getByText(String(value))).toBeInTheDocument();
  }
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("posts only an empty body and the public read key to the dedicated endpoint", async () => {
  const response = result();
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(response)));
  vi.stubGlobal("fetch", fetcher);
  expect(await client().publicDemoETL()).toEqual(response);
  expect(fetcher).toHaveBeenCalledTimes(1);
  const [url, options] = fetcher.mock.calls[0];
  expect(url).toBe(publicPath);
  expect(options.method).toBe("POST");
  expect(options.headers).toEqual({ "X-API-Key": "public-test", "Content-Type": "application/json" });
  expect(JSON.parse(options.body)).toEqual({});
  expect(options.credentials).toBe("omit");
  expect(options.redirect).toBe("error");
});

it("runs only on click, blocks rapid clicks while pending, and displays actual counters", async () => {
  const api = client();
  let finish!: (value: Envelope<DemoETLResult>) => void;
  const pending = new Promise<Envelope<DemoETLResult>>(resolve => { finish = resolve; });
  const call = vi.spyOn(api, "publicDemoETL").mockReturnValue(pending);
  const refresh = vi.fn().mockResolvedValue(undefined);
  render(<DemoETLAction client={api} onRefresh={refresh} />);
  expect(call).not.toHaveBeenCalled();
  const button = screen.getByRole("button", { name: "Run ETL" });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(call).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Running ETL" })).toBeDisabled();
  expect(screen.getByText("Processing simulated telemetry...")).toBeInTheDocument();

  await act(async () => { finish(result()); });
  await waitFor(() => expect(screen.getByRole("button", { name: "Run ETL" })).toBeEnabled());
  expect(refresh).toHaveBeenCalledTimes(1);
  expectCounts(result().data);
});

it("allows another run immediately after completion and displays its zero-insert duplicate counts", async () => {
  const api = client();
  const second = result("demo-run-2");
  second.data.counts = { extracted: 14, accepted: 13, inserted: 0, duplicated: 13, rejected: 1 };
  const call = vi.spyOn(api, "publicDemoETL").mockResolvedValueOnce(result()).mockResolvedValueOnce(second);
  const refresh = vi.fn().mockResolvedValue(undefined);
  render(<DemoETLAction client={api} onRefresh={refresh} />);
  await userEvent.click(screen.getByRole("button", { name: "Run ETL" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Run ETL" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "Run ETL" }));
  await screen.findByText("Run demo-run-2");
  await waitFor(() => expect(screen.getByRole("button", { name: "Run ETL" })).toBeEnabled());
  expect(call).toHaveBeenCalledTimes(2);
  expect(refresh).toHaveBeenCalledTimes(2);
  expectCounts(second.data);
});

it("explains a disabled public demo without falling back to an admin endpoint or retrying", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(
    JSON.stringify({ error: { code: "DEMO_PUBLIC_ETL_DISABLED", message: "private-detail" } }),
    { status: 503 },
  ));
  vi.stubGlobal("fetch", fetcher);
  const refresh = vi.fn();
  render(<DemoETLAction client={client()} onRefresh={refresh} />);
  expect(fetcher).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Run ETL" }));
  await screen.findByText("Run ETL is not enabled for this demo. Existing run history is still available.");
  expect(screen.getByRole("button", { name: "Run ETL" })).toBeEnabled();
  expect(screen.queryByText("private-detail")).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBe(publicPath);
  expect(refresh).not.toHaveBeenCalled();
});

it.each([
  [401, "Demo access could not be verified."],
  [403, "Demo access could not be verified."],
  [404, "This backend does not provide the public ETL demo yet."],
  [409, "Another simulated telemetry run is in progress."],
  [422, "The demo request was rejected."],
  [503, "The demo request could not complete."],
  [504, "The request timed out."],
] as const)("explains HTTP %s failures and permits an explicit next click without automatic retries", async (status, message) => {
  const api = client();
  const call = vi.spyOn(api, "publicDemoETL").mockRejectedValue(new APIError(status));
  const refresh = vi.fn();
  render(<DemoETLAction client={api} onRefresh={refresh} />);
  await userEvent.click(screen.getByRole("button", { name: "Run ETL" }));
  await screen.findByText(text => text.startsWith(message));
  expect(screen.getByRole("button", { name: "Run ETL" })).toBeEnabled();
  expect(call).toHaveBeenCalledTimes(1);
  expect(refresh).not.toHaveBeenCalled();
});

it("reports a recorded FAILED result and refreshes audit history without claiming success", async () => {
  const api = client();
  const failed = result();
  failed.data.status = "FAILED";
  failed.data.error_code = "DATABASE_ERROR";
  vi.spyOn(api, "publicDemoETL").mockResolvedValue(failed);
  const refresh = vi.fn().mockResolvedValue(undefined);
  render(<DemoETLAction client={api} onRefresh={refresh} />);
  await userEvent.click(screen.getByRole("button", { name: "Run ETL" }));
  await screen.findByText("ETL run failed");
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  expect(screen.getByText("FAILED")).toBeInTheDocument();
  expect(screen.queryByText("SUCCEEDED")).not.toBeInTheDocument();
  expectCounts(failed.data);
});

it("keeps the actual run result visible when history refresh fails", async () => {
  const api = client();
  const call = vi.spyOn(api, "publicDemoETL").mockResolvedValue(result());
  render(<DemoETLAction client={api} onRefresh={vi.fn().mockRejectedValue(new Error("private-refresh-detail"))} />);
  await userEvent.click(screen.getByRole("button", { name: "Run ETL" }));
  await screen.findByText("History refresh unavailable");
  expect(screen.getByText("SUCCEEDED")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run ETL" })).toBeEnabled();
  expect(screen.queryByText("private-refresh-detail")).not.toBeInTheDocument();
  expect(call).toHaveBeenCalledTimes(1);
  expectCounts(result().data);
});

it("sanitizes unexpected errors without inventing a run result", async () => {
  const api = client();
  vi.spyOn(api, "publicDemoETL").mockRejectedValue(new Error("private-request-detail"));
  render(<DemoETLAction client={api} onRefresh={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Run ETL" }));
  await screen.findByText("ETL request unavailable");
  expect(screen.queryByText("private-request-detail")).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "ETL run result" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run ETL" })).toBeEnabled();
});

it("does not refresh another page after navigating away during a run", async () => {
  const api = client();
  let finish!: (value: Envelope<DemoETLResult>) => void;
  vi.spyOn(api, "publicDemoETL").mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const refresh = vi.fn();
  const view = render(<DemoETLAction client={api} onRefresh={refresh} />);
  await userEvent.click(screen.getByRole("button", { name: "Run ETL" }));
  view.unmount();
  await act(async () => { finish(result()); });
  expect(refresh).not.toHaveBeenCalled();
});

it.each([false, true])("refreshes Pipeline history and latest results after each run (existing history: %s)", async populated => {
  const run = (data: DemoETLResult): Run => ({
    run_id: data.run_id, source_id: data.source_id, status: data.status,
    requested_window_start: data.window_start, requested_window_end: data.window_end,
    started_at: data.window_end, finished_at: data.window_end,
    records_extracted: data.counts.extracted, records_accepted: data.counts.accepted,
    records_inserted: data.counts.inserted, records_duplicated: data.counts.duplicated,
    records_rejected: data.counts.rejected, watermark_after: data.watermark_after,
  });
  let rows: Run[] = populated ? [run(result("operator-old-run").data)] : [];
  let posts = 0;
  const fetcher = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname === "/api/v1/etl/runs" && options?.method === "GET") {
      const data = url.searchParams.has("status") ? rows.filter(row => row.status === "SUCCEEDED").slice(0, 1) : rows;
      return new Response(JSON.stringify({ data, meta: { request_id: "test" } }));
    }
    if (url.pathname === publicPath && options?.method === "POST") {
      const response = result("demo-run-" + ++posts);
      if (posts === 2) response.data.counts = { extracted: 14, accepted: 13, inserted: 0, duplicated: 13, rejected: 1 };
      rows = [run(response.data), ...rows];
      return new Response(JSON.stringify(response));
    }
    throw new Error("Unexpected Pipeline request");
  });
  vi.stubGlobal("fetch", fetcher);
  window.history.replaceState(null, "", "#/pipeline");
  render(<App />);
  await screen.findByRole("button", { name: "Run ETL" });
  expect(posts).toBe(0);
  if (!populated) expect(screen.getByText("No ETL audit runs exist for this source.")).toBeInTheDocument();

  for (const attempt of [1, 2]) {
    await userEvent.click(screen.getByRole("button", { name: "Run ETL" }));
    await screen.findByText("Run demo-run-" + attempt);
    await screen.findByTitle("demo-run-" + attempt);
    await waitFor(() => expect(screen.getByRole("button", { name: "Run ETL" })).toBeEnabled());
    const latest = screen.getByRole("heading", { name: "Latest ingestion cycle" }).closest(".latest-run")!;
    expect(within(latest as HTMLElement).getByText(new RegExp("demo-run-" + attempt))).toBeInTheDocument();
    expect(posts).toBe(attempt);
  }
  expect(screen.queryByText("No ETL audit runs exist for this source.")).not.toBeInTheDocument();
  expectCounts({ ...result().data, counts: { extracted: 14, accepted: 13, inserted: 0, duplicated: 13, rejected: 1 } });
  for (const [url, options] of fetcher.mock.calls) {
    expect(String(url)).not.toMatch(/\/api\/v1\/(?:demo\/etl\/run|etl\/run)(?:$|\?)/);
    expect(options?.headers).not.toHaveProperty("X-Admin-Key");
  }
});
