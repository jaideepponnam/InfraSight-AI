import { Button, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@carbon/react";
import type { Incident, MonitoredService } from "./types";
import { LifecycleTag, SRETime } from "./shared";

export function IncidentTable({ incidents, services, onSelect, label = "Incidents" }: {
  incidents: Incident[]; services: MonitoredService[]; onSelect: (id: string) => void; label?: string;
}) {
  return <div className="table-scroll sre-table-scroll" tabIndex={0} role="region" aria-label={label + " table"}>
    <Table size="lg" aria-label={label}><TableHead><TableRow>
      {["Incident", "Service", "Severity", "Lifecycle", "Detected"].map(title => <TableHeader key={title}>{title}</TableHeader>)}
    </TableRow></TableHead><TableBody>
      {incidents.map(incident => <TableRow key={incident.id}>
        <TableCell><Button kind="ghost" size="sm" className="sre-incident-link" onClick={() => onSelect(incident.id)} aria-label={"Investigate incident " + incident.id}>
          {incident.title}
        </Button><code className="sre-record-id">{incident.id}</code></TableCell>
        <TableCell>{services.find(service => service.id === incident.service_id)?.service_key ?? incident.service_id}</TableCell>
        <TableCell><span className="sre-severity">{incident.severity}</span></TableCell>
        <TableCell><LifecycleTag state={incident.state} /></TableCell>
        <TableCell><SRETime value={incident.detected_at} /></TableCell>
      </TableRow>)}
    </TableBody></Table>
  </div>;
}
