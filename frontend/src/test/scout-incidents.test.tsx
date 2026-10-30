import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import App, { AIAnalyst } from "../App";
import { APIClient, APIError, aiBody, snapshot } from "../api";
import type { AIResponse } from "../types";
import { envelope, events, evidence, incident, service } from "./sre.fixtures";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const answer: AIResponse = {
  answer: `Incident ${incident.id}: historical recovery VERIFIED; current observation state STALE.`,
  request_id: "investigation-request",
  evidence: { tools_used: ["get_sre_incident_evidence"], reference_time: "2026-10-29T10:00:00Z",
    window: { start: null, end: null }, freshness: { threshold_seconds: 15 },
    currency: null, coverage: [], tool_results: [] },
};

function openScout(id = incident.id) {
  window.history.replaceState(null, "", "#/scout/incidents/" + id);
  const latest = vi.spyOn(APIClient.prototype, "latestSuccessfulRun");
  const ask = vi.spyOn(APIClient.prototype, "ask").mockResolvedValue(answer);
  render(<App />);
  return { latest, ask };
}

it("sends only typed incident scope with the existing public read header", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(answer)));
  vi.stubGlobal("fetch", fetcher);
  await new APIClient("public-demo-read").ask("  Investigate  ", { analysis_scope: "incidents", incident_id: incident.id });
  const [url, options] = fetcher.mock.calls[0];
  expect(url).toBe("/api/v1/ai/query");
  expect(options.headers).toEqual({ "X-API-Key": "public-demo-read", "Content-Type": "application/json" });
  expect(JSON.parse(options.body)).toEqual({ question: "Investigate", analysis_scope: "incidents", incident_id: incident.id });
  expect(options.credentials).toBe("omit");
  expect(aiBody("Fleet", snapshot())).toHaveProperty("reference_time", snapshot().reference_time);
});

it("opening an investigation fills context without AI, ETL, or evidence requests", async () => {
  const { latest, ask } = openScout();
  expect(screen.getByLabelText("Incident ID (optional for listing)")).toHaveValue(incident.id);
  expect((screen.getByLabelText("Ask Scout") as HTMLTextAreaElement).value).toContain("Investigate this incident");
  expect(screen.getByText("Stored observations")).toBeInTheDocument();
  expect(latest).not.toHaveBeenCalled();
  expect(ask).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Analyze" }));
  expect(ask).toHaveBeenCalledWith(expect.stringContaining("Investigate this incident"), { analysis_scope: "incidents", incident_id: incident.id });
  await screen.findByText(/current observation state STALE/);
  expect(screen.getByText(/Historical verified recovery does not establish current health/)).toBeInTheDocument();
  expect(screen.queryByText("Currency")).not.toBeInTheDocument();
  expect(screen.queryByText("Analysis window")).not.toBeInTheDocument();
});

it("Investigate with Scout link navigates from actual incident details without submitting", async () => {
  window.history.replaceState(null, "", "#/incidents/" + incident.id);
  vi.spyOn(APIClient.prototype, "sreIncident").mockResolvedValue(envelope(incident));
  vi.spyOn(APIClient.prototype, "sreEvents").mockResolvedValue(envelope(events));
  vi.spyOn(APIClient.prototype, "sreEvidence").mockResolvedValue(envelope(evidence));
  vi.spyOn(APIClient.prototype, "sreServices").mockResolvedValue(envelope([service]));
  const ask = vi.spyOn(APIClient.prototype, "ask");
  render(<App />);
  const link = await screen.findByRole("link", { name: "Investigate with Scout" });
  expect(link).toHaveAttribute("href", "#/scout/incidents/" + incident.id);
  await act(async () => { window.location.hash = link.getAttribute("href")!; });
  await screen.findByLabelText("Incident ID (optional for listing)");
  expect(ask).not.toHaveBeenCalled();
});

it("scope switching preserves analytics and permits incident investigation without ETL availability", async () => {
  window.history.replaceState(null, "", "#/scout");
  vi.spyOn(APIClient.prototype, "latestSuccessfulRun").mockRejectedValue(new APIError(503));
  const ask = vi.spyOn(APIClient.prototype, "ask").mockResolvedValue(answer);
  render(<App />);
  await screen.findByText("Request unavailable");
  await userEvent.selectOptions(screen.getByLabelText("Investigation scope"), "incidents");
  await userEvent.click(screen.getByRole("button", { name: /List recorded incidents/ }));
  expect(ask).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Analyze" }));
  expect(ask).toHaveBeenCalledWith("List recorded incidents and their lifecycle status.", { analysis_scope: "incidents" });
});

it.each([401, 403, 503])("sanitizes incident query HTTP %s errors without an invented answer", async status => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: status === 503 ? "SRE_DISABLED" : "private-secret" } }), { status })));
  const client = new APIClient("public-read");
  render(<AIAnalyst client={client} context={snapshot()} state="STALE" investigation incidentId={incident.id} />);
  await userEvent.click(screen.getByRole("button", { name: "Analyze" }));
  await screen.findByText("Request unavailable");
  if (status === 503) expect(screen.getByText(/SRE investigation is disabled on this backend/)).toBeInTheDocument();
  expect(screen.queryByText(/private-secret/)).not.toBeInTheDocument();
  expect(screen.queryByText(/ANALYST ASSESSMENT/)).not.toBeInTheDocument();
});

it("rejects malformed incident links before making a provider request", async () => {
  const { ask } = openScout("invalid-uuid");
  expect(screen.getByRole("button", { name: "Analyze" })).toBeDisabled();
  expect(ask).not.toHaveBeenCalled();
});

it("retains the answered context and warns when the incident selection changes", async () => {
  openScout();
  await userEvent.click(screen.getByRole("button", { name: "Analyze" }));
  await screen.findByText(/current observation state STALE/);
  await userEvent.clear(screen.getByLabelText("Incident ID (optional for listing)"));
  await waitFor(() => expect(screen.getByText(/This answer belongs to an earlier context/)).toBeInTheDocument());
});

it("switching back to analytics restores the established ETL context without submitting", async () => {
  const { latest, ask } = openScout();
  latest.mockResolvedValue(null);
  vi.spyOn(APIClient.prototype, "overview").mockResolvedValue(envelope({
    inventory_servers: 0, reporting_servers: 0, healthy_servers: 0, warning_servers: 0,
    critical_servers: 0, stale_servers: 0, no_data_servers: 0, average_cpu_percent: null,
    average_memory_percent: null, average_storage_percent: null, observed_cost: null,
    latest_telemetry_timestamp: null, highest_cpu_server: null, highest_cost_server: null,
    coverage: { estimated_cost: null, currency: "USD", observation_count: 0,
      reporting_server_count: 0, expected_server_count: 0, coverage_fraction: null,
      cost_coverage_fraction: null, overlap_detected: false },
  }));
  await userEvent.selectOptions(screen.getByLabelText("Investigation scope"), "analytics");
  await waitFor(() => expect(latest).toHaveBeenCalledWith("simulated-cloud"));
  await userEvent.click(screen.getByRole("button", { name: /How is our infrastructure doing/ }));
  expect(ask).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Analyze" }));
  expect(ask).toHaveBeenCalledWith("How is our infrastructure doing?", expect.objectContaining({ source_id: "simulated-cloud", currency: "USD" }));
  expect(ask.mock.calls[0][1]).not.toHaveProperty("analysis_scope");
});
