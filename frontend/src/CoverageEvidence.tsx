import { percent } from "./format";
import type { AIResponse } from "./types";

const labels: Record<string, string> = {
  kind: "Evidence type",
  coverage_fraction: "Observation-time coverage",
  cost_coverage_fraction: "Priced observation-time coverage",
  expected_server_count: "Expected servers",
  reporting_server_count: "Reporting servers",
};

export function CoverageEvidence({
  coverage,
}: {
  coverage: AIResponse["evidence"]["coverage"];
}) {
  return (
    <section aria-label="Coverage backend evidence">
      <div className="section-label">COVERAGE · BACKEND EVIDENCE</div>
      {coverage.length ? (
        <ol className="coverage-list">
          {coverage.map((record, index) => (
            <li className="coverage-evidence" key={index}>
              <h3>Evidence {index + 1}</h3>
              {Object.keys(record).length ? (
                <dl>
                  {Object.entries(record).map(([key, value]) => (
                    <div key={key}>
                      <dt>{labels[key] ?? key.replaceAll("_", " ")}</dt>
                      <dd>
                        {key.endsWith("fraction")
                          ? percent(value, true)
                          : value == null
                            ? "Not available"
                            : typeof value === "object"
                              ? JSON.stringify(value)
                              : String(value)}
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="support">No coverage fields supplied.</p>
              )}
            </li>
          ))}
        </ol>
      ) : (
        <p className="support">
          Coverage was not supplied by the selected tools.
        </p>
      )}
    </section>
  );
}
