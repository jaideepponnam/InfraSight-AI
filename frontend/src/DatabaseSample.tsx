import { Accordion, AccordionItem, Tile } from "@carbon/react";

export function DatabaseSample() {
  return (
    <Tile className="panel database-sample">
      <Accordion>
        <AccordionItem title="Sample database ? for reference" open={false}>
          <p className="support">
            An illustration of how server measurements look in PostgreSQL.
            These example rows are fictional, not live analytics.
          </p>
          <div className="table-scroll" tabIndex={0} aria-label="Illustrative database sample">
            <table>
              <thead><tr><th>Server</th><th>Region</th><th>Environment</th><th>CPU</th><th>Memory</th><th>Recorded health</th></tr></thead>
              <tbody>
                <tr><td>app-server-01</td><td>us-south</td><td>prod</td><td>42%</td><td>55%</td><td>HEALTHY</td></tr>
                <tr><td>app-server-02</td><td>eu-de</td><td>staging</td><td>85%</td><td>68%</td><td>WARNING</td></tr>
              </tbody>
            </table>
          </div>
          <p className="support">
            Seven tables organize the data: regions, servers, raw telemetry,
            cleaned infrastructure metrics, ETL runs, rejected records, and ingestion progress.
            Original events are preserved separately from cleaned measurements;
            run history records what the pipeline processed.
          </p>
        </AccordionItem>
      </Accordion>
    </Tile>
  );
}
