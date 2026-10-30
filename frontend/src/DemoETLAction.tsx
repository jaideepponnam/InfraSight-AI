import { Tile } from "@carbon/react";

export function DemoETLAction() {
  return (
    <Tile className="demo-etl">
      <div className="panel-title">
        <h2>Demo ingestion</h2>
      </div>
      <p className="support">
        Telemetry ingestion is managed by an operator. This page displays recorded runs. Refresh to view new results.
      </p>
    </Tile>
  );
}
