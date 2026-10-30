import { afterEach, describe, expect, it, vi } from "vitest";
import { APIClient } from "../api";
import { envelope, events, evidence, incident, service, uid } from "./sre.fixtures";
afterEach(() => vi.unstubAllGlobals());

describe("SRE read API contracts", () => {
  it("canonicalizes valid uppercase UUID links to the backend UUID representation", async () => {
    const canonical = "abcdef01-abcd-4000-8000-abcdef123456";
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(envelope({ ...incident, id: canonical }))));
    vi.stubGlobal("fetch", fetcher);
    expect((await new APIClient().sreIncident(canonical.toUpperCase())).data.id).toBe(canonical);
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/sre/incidents/" + canonical);
  });
  it("uses only GET and public read authorization across the six read contracts", async () => {
    const values = [envelope([service]), envelope([incident], { total: 1, limit: 20, offset: 0 }), envelope(incident), envelope(events), envelope(evidence), envelope(evidence.run)];
    const fetcher = vi.fn();
    values.forEach(value => fetcher.mockResolvedValueOnce(new Response(JSON.stringify(value))));
    vi.stubGlobal("fetch", fetcher);
    const client = new APIClient("public-read", "https://api.example");
    await client.sreServices(); await client.sreIncidents(); await client.sreIncident(incident.id);
    await client.sreEvents(incident.id); const response = await client.sreEvidence(incident.id); await client.sreRun(incident.run_id);
    expect(response.data.probes[0].duration_ms).toBe("12.500");
    expect(fetcher.mock.calls.map(call => call[0])).toEqual([
      "https://api.example/api/v1/sre/services", "https://api.example/api/v1/sre/incidents?limit=20&offset=0",
      "https://api.example/api/v1/sre/incidents/" + incident.id,
      "https://api.example/api/v1/sre/incidents/" + incident.id + "/events",
      "https://api.example/api/v1/sre/incidents/" + incident.id + "/evidence",
      "https://api.example/api/v1/sre/demo-runs/" + incident.run_id,
    ]);
    for (const [, options] of fetcher.mock.calls) {
      expect(options.method).toBe("GET"); expect(options.headers).toEqual({ "X-API-Key": "public-read" });
      expect(options.body).toBeUndefined(); expect(options.credentials).toBe("omit"); expect(options.redirect).toBe("error");
    }
  });
  it("uses backend filters and flat pagination metadata", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(envelope([incident], { total: 41, limit: 20, offset: 20 }))));
    vi.stubGlobal("fetch", fetcher);
    const result = await new APIClient().sreIncidents({ state: "RESOLVED", offset: 20, limit: 20 });
    expect(fetcher.mock.calls[0][0]).toContain("limit=20&offset=20&state=RESOLVED");
    expect(result.meta.total).toBe(41);
  });
  it.each([401, 403, 404, 503])("sanitizes HTTP %s without relaying server error text", async status => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"error":{"code":"PRIVATE","message":"private-secret"}}', { status, headers: { "X-Request-ID": uid(90) } })));
    await expect(new APIClient().sreServices()).rejects.toMatchObject({ status, requestId: uid(90), code: undefined });
    await expect(new APIClient().sreServices()).rejects.not.toThrow("private-secret");
  });
  it("distinguishes a disabled incident engine", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"error":{"code":"SRE_DISABLED"}}', { status: 503 })));
    await expect(new APIClient().sreServices()).rejects.toMatchObject({ status: 503, code: "SRE_DISABLED" });
  });
  it.each([{}, { data: [service], meta: {} }, envelope([{ ...incident, state: "MAGIC" }], { total: 1, limit: 20, offset: 0 }), envelope([incident], { total: null, limit: 20, offset: 0 })])("rejects malformed incident envelopes", async payload => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))));
    await expect(new APIClient().sreIncidents()).rejects.toMatchObject({ status: 502 });
  });
  it("rejects cross-resource observations and wrong incident records", async () => {
    const changed = structuredClone(evidence); changed.probes[0].run_id = uid(999);
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(envelope(changed))))
      .mockResolvedValueOnce(new Response(JSON.stringify(envelope({ ...incident, id: uid(999) }))));
    vi.stubGlobal("fetch", fetcher);
    await expect(new APIClient().sreEvidence(incident.id)).rejects.toMatchObject({ status: 502 });
    await expect(new APIClient().sreIncident(incident.id)).rejects.toMatchObject({ status: 502 });
  });
  it("rejects invalid IDs before fetching any path", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    await expect(new APIClient().sreIncident("../etl/run")).rejects.toMatchObject({ status: 422 });
    expect(fetcher).not.toHaveBeenCalled();
  });
});
