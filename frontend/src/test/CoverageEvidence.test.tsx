import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { CoverageEvidence } from "../CoverageEvidence";

describe("coverage evidence", () => {
  it("keeps matching metrics and repeated records separately, including records after the fourth", () => {
    const record = {
      kind: "period_cost",
      coverage_fraction: "0.993",
      cost_coverage_fraction: "0.993",
      reporting_server_count: 75,
      expected_server_count: 75,
    };
    render(<CoverageEvidence coverage={Array.from({ length: 5 }, () => ({ ...record }))} />);
    const region = within(screen.getByRole("region", { name: "Coverage backend evidence" }));
    const records = region.getAllByRole("listitem");
    expect(records).toHaveLength(5);
    records.forEach((element, index) => {
      const row = within(element);
      expect(row.getByRole("heading", { name: `Evidence ${index + 1}` })).toBeInTheDocument();
      expect(row.getByText("Evidence type").nextElementSibling).toHaveTextContent("period_cost");
      expect(row.getByText("Observation-time coverage").nextElementSibling).toHaveTextContent("99.3%");
      expect(row.getByText("Priced observation-time coverage").nextElementSibling).toHaveTextContent("99.3%");
      expect(row.getByText("Reporting servers").nextElementSibling).toHaveTextContent("75");
      expect(row.getByText("Expected servers").nextElementSibling).toHaveTextContent("75");
      expect(row.getAllByRole("term")).toHaveLength(5);
      expect(row.getAllByRole("definition")).toHaveLength(5);
    });
  });

  it("renders empty coverage without inventing metrics", () => {
    render(<CoverageEvidence coverage={[]} />);
    expect(screen.getByText("Coverage was not supplied by the selected tools.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.queryByText(/99\.3%/)).not.toBeInTheDocument();
  });

  it("preserves unknown fields, exact strings, zero and false while labeling unavailable values", () => {
    render(<CoverageEvidence coverage={[{
      coverage_fraction: null,
      cost_coverage_fraction: "0",
      reporting_server_count: 0,
      overlap_detected: false,
      custom_evidence: "12345678901234567890.12345678",
      future_metadata: { source: "backend" },
    }]} />);
    expect(screen.getByText("Observation-time coverage").nextElementSibling).toHaveTextContent("Not available");
    expect(screen.getByText("Priced observation-time coverage").nextElementSibling).toHaveTextContent("0.0%");
    expect(screen.getByText("Reporting servers").nextElementSibling).toHaveTextContent("0");
    expect(screen.getByText("overlap detected").nextElementSibling).toHaveTextContent("false");
    expect(screen.getByText("custom evidence").nextElementSibling).toHaveTextContent("12345678901234567890.12345678");
    expect(screen.getByText("future metadata").nextElementSibling).toHaveTextContent('{"source":"backend"}');
  });

  it("keeps an empty backend record visible", () => {
    render(<CoverageEvidence coverage={[{}]} />);
    expect(screen.getByRole("listitem")).toHaveTextContent("No coverage fields supplied.");
  });
});
