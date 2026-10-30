import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { APIClient, APIError } from "../api";
import { IncidentCenter } from "../sre/IncidentCenter";
import { IncidentDetails } from "../sre/IncidentDetails";
import { LiveOperations } from "../sre/LiveOperations";
import { activeRecords, envelope, epoch, events, evidence, incident, now, service, uid } from "./sre.fixtures";

function mockReads() {
  const reads = {
    services: vi.spyOn(APIClient.prototype, "sreServices").mockResolvedValue(envelope([service])),
    incidents: vi.spyOn(APIClient.prototype, "sreIncidents").mockResolvedValue(envelope([incident], { total: 1, limit: 20, offset: 0 })),
    detail: vi.spyOn(APIClient.prototype, "sreIncident").mockResolvedValue(envelope(incident)),
    events: vi.spyOn(APIClient.prototype, "sreEvents").mockResolvedValue(envelope(events)),
    evidence: vi.spyOn(APIClient.prototype, "sreEvidence").mockResolvedValue(envelope(evidence)),
  };
  return reads;
}
const props = () => ({ client: new APIClient("public-read"), refresh: 0, onRefresh: vi.fn(), onSelect: vi.fn(), onBusy: vi.fn() });
beforeEach(() => vi.spyOn(Date, "now").mockReturnValue(now));
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Live Operations", () => {
  it("renders API service metadata and marks old evidence stale, separate from incident resolution", async () => {
    mockReads(); vi.spyOn(Date, "now").mockReturnValue(epoch + 100_000);
    const parameters = props();
    render(<LiveOperations {...parameters} />);
    await screen.findByRole("heading", { name: service.service_key });
    expect(screen.getByText("STALE")).toBeInTheDocument();
    const serviceCard = screen.getByRole("heading", { name: service.service_key }).closest(".sre-service") as HTMLElement;
    expect(within(serviceCard).getByText("RESOLVED")).toBeInTheDocument();
    expect(screen.queryByText("HEALTHY", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText(/does not run probes/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "View incident" }));
    expect(parameters.onSelect).toHaveBeenCalledWith(incident.id);
  });
  it("does not infer healthy operation when a registered service has no incident evidence", async () => {
    const reads = mockReads();
    reads.incidents.mockResolvedValue(envelope([], { total: 0, limit: 100, offset: 0 }));
    render(<LiveOperations {...props()} />);
    await screen.findByText("UNKNOWN");
    expect(reads.evidence).not.toHaveBeenCalled();
    expect(screen.getByText(/No service observation is available/)).toBeInTheDocument();
  });
  it("shows actual fresh controlled degradation and ages it without new HTTP requests", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    let clock = now; vi.spyOn(Date, "now").mockImplementation(() => clock);
    const reads = mockReads(); const active = activeRecords();
    reads.incidents.mockResolvedValue(envelope([active.incident], { total: 1, limit: 100, offset: 0 }));
    reads.evidence.mockResolvedValue(envelope(active.evidence));
    render(<LiveOperations {...props()} />);
    await screen.findByText("DEGRADED");
    const openMetric = screen.getByText("Open in loaded records").parentElement!;
    expect(within(openMetric).getByText("1", { exact: true })).toBeInTheDocument();
    clock = epoch + 30_000;
    await act(async () => vi.advanceTimersByTime(1000));
    expect(screen.getByText("STALE")).toBeInTheDocument();
    expect(reads.evidence).toHaveBeenCalledTimes(1);
    expect(reads.incidents).toHaveBeenCalledTimes(1);
  });
  it("keeps a service unknown when its evidence request fails", async () => {
    const reads = mockReads(); reads.evidence.mockRejectedValue(new APIError(503, uid(91)));
    render(<LiveOperations {...props()} />);
    await screen.findByText("Service evidence unavailable");
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
    expect(screen.getByText(uid(91))).toBeInTheDocument();
  });
  it("handles an empty registry honestly", async () => {
    const reads = mockReads(); reads.services.mockResolvedValue(envelope([]));
    render(<LiveOperations {...props()} />);
    await screen.findByRole("heading", { name: "No monitored services returned" });
    expect(screen.queryByRole("button", { name: "View incident" })).not.toBeInTheDocument();
  });
  it.each([401, 403, 503])("shows HTTP %s without invented service cards", async status => {
    const reads = mockReads(); reads.services.mockRejectedValue(new APIError(status, uid(92), status === 503 ? "SRE_DISABLED" : undefined));
    render(<LiveOperations {...props()} />);
    await screen.findByText(status === 503 ? "Incident engine disabled" : "Read access unavailable");
    expect(screen.queryByRole("heading", { name: service.service_key })).not.toBeInTheDocument();
    expect(screen.queryByText("No monitored services returned")).not.toBeInTheDocument();
  });
  it("renders loading without service or health claims", async () => {
    const reads = mockReads(); reads.services.mockImplementation(() => new Promise(() => {}));
    render(<LiveOperations {...props()} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText("HEALTHY", { exact: true })).not.toBeInTheDocument();
  });
});

describe("Incident Center", () => {
  it("renders severity, lifecycle, timestamps, and service names from API records", async () => {
    mockReads(); const parameters = props(); render(<IncidentCenter {...parameters} />);
    const table = await screen.findByRole("table", { name: "Incidents" });
    expect(within(table).getByText("SEV3")).toBeInTheDocument();
    expect(within(table).getByText("RESOLVED")).toBeInTheDocument();
    expect(within(table).getByText(service.service_key)).toBeInTheDocument();
    expect(table.querySelector("time")?.getAttribute("datetime")).toBe(incident.detected_at);
    await userEvent.click(within(table).getByRole("button", { name: "Investigate incident " + incident.id }));
    expect(parameters.onSelect).toHaveBeenCalledWith(incident.id);
  });
  it("requests backend pagination and resets the offset when filtering", async () => {
    const reads = mockReads();
    reads.incidents.mockImplementation(async params => envelope(
      [{ ...incident, title: "Record at " + (params?.offset ?? 0) }],
      { total: 21, limit: 20, offset: params?.offset ?? 0 },
    ));
    render(<IncidentCenter {...props()} />);
    await screen.findByText("Record at 0");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Record at 20");
    expect(reads.incidents).toHaveBeenLastCalledWith({ limit: 20, offset: 20 });
    await userEvent.selectOptions(screen.getByLabelText("Lifecycle status"), "DETECTED");
    await waitFor(() => expect(reads.incidents).toHaveBeenLastCalledWith({ state: "DETECTED", limit: 20, offset: 0 }));
  });
  it("supports empty results, registry failure, unauthorized state, and retry", async () => {
    const reads = mockReads();
    reads.incidents.mockRejectedValueOnce(new APIError(401));
    const parameters = props(); const view = render(<IncidentCenter {...parameters} />);
    await screen.findByText("Read access unavailable");
    await userEvent.click(screen.getByRole("button", { name: "Retry retrieval" }));
    expect(parameters.onRefresh).toHaveBeenCalled();
    reads.incidents.mockResolvedValue(envelope([], { total: 0, offset: 0, limit: 20 }));
    reads.services.mockRejectedValue(new APIError(503));
    view.rerender(<IncidentCenter {...parameters} refresh={1} />);
    await screen.findByRole("heading", { name: "No incidents returned" });
    expect(screen.getByText("Service names unavailable; identifiers are shown")).toBeInTheDocument();
  });
});

describe("Incident Details", () => {
  it("rejects an invalid incident link before requesting any records", async () => {
    const reads = mockReads();
    render(<IncidentDetails {...props()} id="not-a-uuid" onBack={vi.fn()} />);
    await screen.findByText("This incident link or filter is invalid.");
    for (const read of Object.values(reads)) expect(read).not.toHaveBeenCalled();
  });
  it("clears earlier details when refresh loses read authorization", async () => {
    const reads = mockReads(); const parameters = props();
    const view = render(<IncidentDetails {...parameters} id={incident.id} onBack={vi.fn()} />);
    await screen.findByRole("heading", { name: incident.title });
    reads.evidence.mockRejectedValue(new APIError(401));
    view.rerender(<IncidentDetails {...parameters} refresh={1} id={incident.id} onBack={vi.fn()} />);
    await screen.findByText("Read access unavailable");
    expect(screen.queryByRole("heading", { name: incident.title })).not.toBeInTheDocument();
    expect(screen.queryByText("Verified", { exact: true })).not.toBeInTheDocument();
  });
  it("shows actual observations, timeline, recovery proof and no mutation controls", async () => {
    mockReads(); vi.spyOn(Date, "now").mockReturnValue(epoch + 100_000);
    render(<IncidentDetails {...props()} id={incident.id} onBack={vi.fn()} />);
    await screen.findByRole("heading", { name: incident.title });
    expect(screen.getByText("Verified", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("STALE", { exact: true })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "HTTP observations" }).querySelectorAll("tbody tr")).toHaveLength(10);
    expect(screen.getAllByText("12.500 ms")).toHaveLength(10);
    expect(screen.getByRole("heading", { name: "Event timeline" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "FAULT CLEARED" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^(Recover|Acknowledge|Start exercise|Inject fault)$/i })).not.toBeInTheDocument();
    expect(screen.queryByText("LIVE", { exact: true })).not.toBeInTheDocument();
  });
  it("does not claim verification on an unsuccessful attempt", async () => {
    const reads = mockReads(); const changed = structuredClone(evidence);
    changed.recovery_attempts[0].status = "FAILED";
    changed.recovery_attempts[0].error_code = "SRE_RECOVERY_VERIFICATION_FAILED";
    reads.evidence.mockResolvedValue(envelope(changed));
    render(<IncidentDetails {...props()} id={incident.id} onBack={vi.fn()} />);
    await screen.findByText("Failed", { exact: true });
    expect(screen.getAllByText("SRE_RECOVERY_VERIFICATION_FAILED").length).toBeGreaterThan(0);
    expect(screen.queryByText("Verified", { exact: true })).not.toBeInTheDocument();
  });
  it("keeps metadata and timeline available after evidence fails", async () => {
    const reads = mockReads(); reads.evidence.mockRejectedValue(new APIError(503));
    render(<IncidentDetails {...props()} id={incident.id} onBack={vi.fn()} />);
    await screen.findByText("Diagnostic evidence unavailable");
    expect(screen.getByRole("heading", { name: incident.title })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "FAULT CLEARED" })).toBeInTheDocument();
    expect(screen.getByText("Not confirmed", { exact: true })).toBeInTheDocument();
  });
  it("handles unavailable incidents without exposing another record's details", async () => {
    const reads = mockReads(); reads.detail.mockRejectedValue(new APIError(404));
    render(<IncidentDetails {...props()} id={incident.id} onBack={vi.fn()} />);
    await screen.findByText("Incident unavailable");
    expect(screen.queryByRole("heading", { name: incident.title })).not.toBeInTheDocument();
  });
  it("rejects mismatched run evidence rather than drawing a health conclusion", async () => {
    const reads = mockReads(); const changed = structuredClone(evidence);
    changed.run.service_id = uid(999); reads.evidence.mockResolvedValue(envelope(changed));
    render(<IncidentDetails {...props()} id={incident.id} onBack={vi.fn()} />);
    await screen.findByText("Diagnostic evidence unavailable");
    expect(screen.getByText("UNKNOWN", { exact: true })).toBeInTheDocument();
  });
});

describe("application incident navigation", () => {
  it("renders the serialized backend read contracts through the actual typed client", async () => {
    const fetcher = vi.fn(async (url: string) => {
      const path = new URL(url, "http://local.test").pathname;
      const payload = path.endsWith("/services") ? envelope([service])
        : path.endsWith("/events") ? envelope(events)
        : path.endsWith("/evidence") ? envelope(evidence)
        : path.endsWith("/incidents/" + incident.id) ? envelope(incident) : undefined;
      if (!payload) throw new Error("Unexpected API request");
      return new Response(JSON.stringify(payload));
    });
    vi.stubGlobal("fetch", fetcher);
    window.history.replaceState(null, "", "#/incidents/" + incident.id);
    render(<App />);
    await screen.findByRole("heading", { name: incident.title });
    expect(screen.getByText("Verified", { exact: true })).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(4);
    for (const call of fetcher.mock.calls as unknown as [string, RequestInit][]) {
      expect(call[0]).toMatch(/^\/api\/v1\/sre\//);
      expect(call[1].method).toBe("GET");
      expect(Object.keys(call[1].headers!)).toEqual(["X-API-Key"]);
      expect(call[1].body).toBeUndefined();
    }
  });
  it("supports direct SRE links, details, back navigation, refresh and legacy destinations without ETL dependency", async () => {
    const reads = mockReads();
    const etl = vi.spyOn(APIClient.prototype, "latestSuccessfulRun").mockRejectedValue(new APIError(503));
    window.history.replaceState(null, "", "#/incidents");
    render(<App />);
    await screen.findByRole("table", { name: "Incidents" });
    expect(etl).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Investigate incident " + incident.id }));
    await screen.findByRole("heading", { name: incident.title });
    expect(window.location.hash).toBe("#/incidents/" + incident.id);
    expect(reads.detail).toHaveBeenCalledWith(incident.id);
    expect(screen.getByText("Read only")).toBeInTheDocument();
    expect(screen.queryByText("LIVE", { exact: true })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Refresh SRE evidence" }));
    await waitFor(() => expect(reads.detail).toHaveBeenCalledTimes(2));
    await userEvent.click(screen.getByRole("button", { name: "Back to Incident Center" }));
    await screen.findByRole("table", { name: "Incidents" });
    expect(window.location.hash).toBe("#/incidents");
    for (const name of ["Overview", "Pipeline", "Scout", "Live Operations", "Incident Center"]) expect(screen.getByRole("button", { name })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Overview" }));
    await waitFor(() => expect(etl).toHaveBeenCalled());
  });
  it("responds to browser history events and ignores late results from another incident", async () => {
    const reads = mockReads(); const second = { ...incident, id: uid(200), title: "Second incident record" };
    let resolveFirst!: (value: ReturnType<typeof envelope<typeof incident>>) => void;
    reads.detail.mockImplementation(id => id === incident.id ? new Promise(resolve => { resolveFirst = resolve; }) : Promise.resolve(envelope(second)));
    reads.events.mockImplementation(async id => envelope(events.map(event => ({ ...event, incident_id: id }))));
    reads.evidence.mockRejectedValue(new APIError(503));
    window.history.replaceState(null, "", "#/incidents/" + incident.id);
    render(<App />);
    await waitFor(() => expect(reads.detail).toHaveBeenCalledWith(incident.id));
    act(() => {
      window.history.replaceState(null, "", "#/incidents/" + second.id);
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await screen.findByRole("heading", { name: second.title });
    await act(async () => resolveFirst(envelope(incident)));
    expect(screen.queryByRole("heading", { name: incident.title })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: second.title })).toBeInTheDocument();
  });
});
