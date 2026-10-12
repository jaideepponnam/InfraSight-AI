import { useEffect, useState } from "react";
import { InlineLoading, InlineNotification, Select, SelectItem, Tag, Tile } from "@carbon/react";
import { APIClient } from "./api";
import { numeric, percent, telemetryState } from "./format";
import type { AverageHealth, Context, Overview, Region } from "./types";

export function HealthPanel({data, regions, context, client}: {data: Overview; regions: Region[]; context: Context; client: APIClient}) {
  const [mode, setMode] = useState<"Live" | "Avg">("Live");
  const [rows, setRows] = useState<AverageHealth[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (mode !== "Avg") return;
    let active = true; setLoading(true); setError(false); setRows([]);
    client.averageHealth(context).then(result => {if(active) setRows(result.data);}).catch(() => {if(active) setError(true);}).finally(() => {if(active) setLoading(false);});
    return () => {active = false;};
  }, [client, context, mode]);
  const fleet = rows.find(row => row.scope_kind === "fleet");
  const avgRegions = rows.filter(row => row.scope_kind === "region");
  const mix = [["Healthy", fleet?.healthy_fraction ?? null, "healthy"], ["Warning", fleet?.warning_fraction ?? null, "warning"], ["Critical", fleet?.critical_fraction ?? null, "critical"]] as const;
  const states = [
    ["Healthy", data.healthy_servers, "healthy"],
    ["Warning", data.warning_servers, "warning"],
    ["Critical", data.critical_servers, "critical"],
    ["Stale", data.stale_servers, "stale"],
    ["No data", data.no_data_servers, "no-data"],
  ] as const;
  return (
        <Tile className="panel">
          <div className="panel-title">
            <h2>Infrastructure health</h2>
            <div className="health-controls"><Select id="health-view" labelText="Health view" hideLabel size="sm" value={mode} onChange={event => setMode(event.target.value as "Live" | "Avg")}><SelectItem value="Live" text="Live" /><SelectItem value="Avg" text="Avg" /></Select>{mode === "Live" && <Tag type="cool-gray" size="sm">{telemetryState(data)}</Tag>}</div>
          </div>
          {mode === "Live" ? <>          <p className="support">
            Health at the latest successful run. Retained until the next run completes.
          </p>
          <div
            className="health-strip"
            role="img"
            aria-label={states
              .map(([label, count]) => label + ": " + count)
              .join(", ")}
          >
            {states
              .filter(([, count]) => count > 0)
              .map(([label, count, tone]) => (
                <span
                  key={label}
                  className={tone}
                  style={{ flex: count }}
                  title={label + ": " + count}
                />
              ))}
          </div>
          <div className="health-legend">
            {states.map(([label, count, tone]) => (
              <div key={label}>
                <i className={tone} />
                <span>{label}</span>
                <b>{count}</b>
              </div>
            ))}
          </div>
          <div className="section-label">REGIONAL FLEET</div>
          {regions.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Region / source</th>
                    <th>Healthy</th>
                    <th>Warning</th>
                    <th>Critical</th>
                    <th>Stale / no data</th>
                  </tr>
                </thead>
                <tbody>
                  {regions.map((r) => (
                    <tr key={r.source_id + r.region_code}>
                      <td>
                        <b>{r.region_code}</b>
                        <small>{r.source_id}</small>
                      </td>
                      <td className="healthy">{r.healthy_servers}</td>
                      <td className="warning">{r.warning_servers}</td>
                      <td className="critical">{r.critical_servers}</td>
                      <td>
                        {r.stale_servers} / {r.no_data_servers}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty">No regional observations in this context.</p>
          )}
</> : <>
            <p className="support">Average health mix, last hour. Observed time percentages, not server counts.</p>
            {loading && <InlineLoading description="Loading average health..." />}
            {error && <InlineNotification kind="warning" hideCloseButton title="Average health unavailable" subtitle="Try refreshing, or select Live." />}
            {!loading && !error && fleet && <>
              {fleet.healthy_fraction == null ? <p className="empty">{fleet.health_overlap_detected ? "Average unavailable: overlapping telemetry intervals." : "No recorded telemetry in this window."}</p> : <>
                <div className="health-strip" role="img" aria-label="Average recorded health distribution">{mix.map(([label, value, tone]) => <span key={label} className={tone} style={{flex: numeric(value)?.toNumber() || 0}} title={label + ": " + percent(value, true)} />)}</div>
                <div className="health-legend">{mix.map(([label, value, tone]) => <div key={label}><i className={tone} /><span>{label}</span><b>{percent(value, true)}</b></div>)}</div>
              </>}
              <p className="support">Recorded time coverage: {percent(fleet.coverage_fraction, true)}. Missing time is not counted as healthy.</p>
              {avgRegions.length > 0 && <div className="table-scroll"><table><thead><tr><th>Region</th><th>Healthy</th><th>Warning</th><th>Critical</th></tr></thead><tbody>{avgRegions.map(row => <tr key={row.source_id + ":" + row.region_code}><td>{row.region_code}</td><td className="healthy">{percent(row.healthy_fraction,true)}</td><td className="warning">{percent(row.warning_fraction,true)}</td><td className="critical">{percent(row.critical_fraction,true)}</td></tr>)}</tbody></table></div>}
            </>}
          </>}
        </Tile>
  );
}
