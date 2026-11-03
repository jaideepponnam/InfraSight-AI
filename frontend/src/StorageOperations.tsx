import { useEffect, useState } from "react";
import { Button, InlineLoading, InlineNotification, Tag, Tile } from "@carbon/react";
import { APIClient, APIError } from "./api";
import { date } from "./format";
import type { Context, StorageServer, StorageServerDetail } from "./types";

function metric(value: string | number | null | undefined) {
  if (value === null || value === undefined) return "No data";
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(1) + "%" : "No data";
}

export function StorageOperations({ client, context }: { client: APIClient; context: Context }) {
  const [nodes, setNodes] = useState<StorageServer[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<StorageServerDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    client.storageServers(context.source_id).then(response => {
      if (active) setNodes(response.data);
    }).catch(e => {
      if (active) setError(e instanceof APIError ? e.message : "Inventory unavailable.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [client, context.source_id]);

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    let active = true;
    setDetail(null);
    setDetailLoading(true);
    setError(null);
    client.storageServer(selected, context).then(response => {
      if (active) setDetail(response.data);
    }).catch(e => {
      if (active) setError(e instanceof APIError ? e.message : "Node details unavailable.");
    }).finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [client, context, selected]);

  const telemetry = detail?.latest_telemetry;
  return <section className="storage-operations">
    <div className="page-heading">
      <div className="eyebrow">STORAGE SRE · SIMULATED TELEMETRY</div>
      <h1>Storage Operations</h1>
      <p>Inspect infrastructure nodes and freshness-aware telemetry from the existing monitoring backend. No recovery actions are performed here.</p>
    </div>
    {error && <InlineNotification kind="error" title="Unable to load" subtitle={error} hideCloseButton lowContrast />}
    {loading ? <InlineLoading description="Loading monitored nodes…" /> : <>
      <Tile className="panel">
        <div className="panel-title"><h2>Monitored node inventory</h2><Tag type="blue">{nodes.length} shown</Tag></div>
        <p className="support">Select a node to inspect its actual recorded telemetry. Inventory is limited to the first 100 simulated-cloud nodes.</p>
        {nodes.length === 0 ? <p className="empty">No nodes found. Run the existing telemetry pipeline first.</p> :
          <div className="table-scroll"><table>
            <thead><tr><th>Node</th><th>Region</th><th>Environment</th><th>Last seen</th><th>Investigate</th></tr></thead>
            <tbody>{nodes.map(node => <tr key={node.server_id}>
              <td><b>{node.server_name}</b></td>
              <td>{node.region_code}</td>
              <td>{node.environment}</td>
              <td>{date(node.last_seen_at)}</td>
              <td><Button kind={selected === node.server_id ? "secondary" : "tertiary"} size="sm" onClick={() => setSelected(node.server_id)}>Inspect node</Button></td>
            </tr>)}</tbody>
          </table></div>}
      </Tile>
      {(selected || detailLoading) && <Tile className="panel storage-detail" aria-live="polite">
        <div className="panel-title"><h2>Node investigation</h2><Button kind="ghost" size="sm" onClick={() => setSelected(null)}>Close</Button></div>
        {detailLoading ? <InlineLoading description="Reading node telemetry…" /> : detail && <>
          <h3>{detail.server_name}</h3>
          <p className="support">{detail.region_code} · {detail.environment} · {detail.source_id}</p>
          <div className="storage-metric-grid">
            <div><small>CPU utilization</small><strong>{metric(telemetry?.cpu_usage_percent)}</strong></div>
            <div><small>Memory utilization</small><strong>{metric(telemetry?.memory_usage_percent)}</strong></div>
            <div><small>Storage utilization</small><strong>{metric(telemetry?.storage_usage_percent)}</strong></div>
            <div><small>Health</small><strong>{telemetry?.effective_health || "NO_DATA"}</strong></div>
          </div>
          <p className="support">Telemetry observed: {date(telemetry?.observed_at)} · Reference: {date(context.reference_time)}</p>
          <p className="support">This view shows measured infrastructure health, not a confirmed storage incident. Incident lifecycle and recovery verification will be added separately.</p>
        </>}
      </Tile>}
    </>}
  </section>;
}
