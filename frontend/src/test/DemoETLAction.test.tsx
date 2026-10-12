import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, afterEach } from "vitest";
import { DemoETLAction } from "../DemoETLAction";
import { APIClient, APIError } from "../api";
import type { DemoETLResult, Envelope } from "../types";

const result: Envelope<DemoETLResult> = { data: {
  run_id: "demo-run", source_id: "simulated-cloud", status: "SUCCEEDED",
  window_start: "2026-10-12T09:00:00Z", window_end: "2026-10-12T09:02:00Z",
  watermark_before: null, watermark_after: "2026-10-12T09:02:00Z",
  counts: { extracted: 300, accepted: 297, inserted: 250, duplicated: 47, rejected: 3 }, error_code: null,
}, meta: { request_id: "test" } };
afterEach(() => vi.unstubAllGlobals());

it("sends only an empty demo body with read authorization", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(result)));
  vi.stubGlobal("fetch", fetcher);
  expect(await new APIClient("public-demo").demoETL()).toEqual(result);
  const [url, options] = fetcher.mock.calls[0];
  expect(url).toBe("/api/v1/demo/etl/run");
  expect(options.method).toBe("POST");
  expect(options.headers).toEqual({ "X-API-Key": "public-demo", "Content-Type": "application/json" });
  expect(JSON.parse(options.body)).toEqual({});
});

it("runs only on click, disables while pending, renders counters and refreshes history", async () => {
  const client = new APIClient();
  let finish!: (value: Envelope<DemoETLResult>) => void;
  const call = vi.spyOn(client, "demoETL").mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const refresh = vi.fn().mockResolvedValue(undefined);
  render(<DemoETLAction client={client} onRefresh={refresh} />);
  expect(call).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Run Demo ETL" }));
  expect(screen.getByRole("button", { name: "Running Demo ETL" })).toBeDisabled();
  expect(screen.getByText("Processing telemetry...")).toBeInTheDocument();
  finish(result);
  await screen.findByText("SUCCEEDED");
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  for (const value of ["300", "297", "250", "47", "3"]) expect(screen.getByText(value)).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("button", { name: "Run Demo ETL" })).toBeEnabled());
  expect(call).toHaveBeenCalledTimes(1);
});

it.each([409, 503, 504, 401])("shows sanitized HTTP %s failure without retrying", async status => {
  const client = new APIClient();
  const call = vi.spyOn(client, "demoETL").mockRejectedValue(new APIError(status));
  const refresh = vi.fn();
  render(<DemoETLAction client={client} onRefresh={refresh} />);
  await userEvent.click(screen.getByRole("button", { name: "Run Demo ETL" }));
  await screen.findByText("Demo ETL unavailable");
  expect(call).toHaveBeenCalledTimes(1);
  expect(refresh).not.toHaveBeenCalled();
});

it("preserves a failed run summary and refreshes its audit history", async () => {
  const client = new APIClient();
  vi.spyOn(client, "demoETL").mockResolvedValue({ ...result, data: { ...result.data, status: "FAILED", error_code: "DATABASE_ERROR" } });
  const refresh = vi.fn().mockResolvedValue(undefined);
  render(<DemoETLAction client={client} onRefresh={refresh} />);
  await userEvent.click(screen.getByRole("button", { name: "Run Demo ETL" }));
  await screen.findByText("Demo ETL failed");
  expect(screen.getByText("FAILED")).toBeInTheDocument();
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
});

it("keeps the run result visible if history refresh fails", async () => {
  const client = new APIClient();
  vi.spyOn(client, "demoETL").mockResolvedValue(result);
  render(<DemoETLAction client={client} onRefresh={vi.fn().mockRejectedValue(new Error("private-error"))} />);
  await userEvent.click(screen.getByRole("button", { name: "Run Demo ETL" }));
  await screen.findByText("History refresh unavailable");
  expect(screen.getByText("SUCCEEDED")).toBeInTheDocument();
  expect(screen.queryByText("private-error")).not.toBeInTheDocument();
});
