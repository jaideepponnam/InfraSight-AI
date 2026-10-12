import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AnalystAnswer } from "../AnalystAnswer";

describe("analyst answer presentation", () => {
  it("renders Markdown hierarchy, emphasis, lists and line breaks", () => {
    const { container } = render(<AnalystAnswer answer={'# Fleet assessment\n\n**Critical** servers require *review*.\n\n- First finding\n- Second finding\n\n1. Inspect telemetry\n2. Confirm workload\n\nFirst line  \nSecond line'} />);
    expect(screen.getByRole("heading", { name: "Fleet assessment" })).toBeInTheDocument();
    expect(container.querySelector("strong")).toHaveTextContent("Critical");
    expect(container.querySelector("em")).toHaveTextContent("review");
    expect(container.querySelectorAll("li")).toHaveLength(4);
    expect(container.querySelector("br")).toBeInTheDocument();
    expect(container.querySelectorAll("p").length).toBeGreaterThan(1);
  });

  it("styles only explicitly labeled facts without changing precise values or semantics", () => {
    const { container } = render(<AnalystAnswer answer={'**Current value:** USD 12345678901234567890.12345678\n\n**Previous value**: USD 1.00000001\n\n- **Coverage:** 99.1% observation-time coverage; 75/75 reporting servers\n- **Health:** STALE / NO_DATA\n\n**Important** interpretation remains unchanged.'} />);
    expect(container.querySelectorAll(".answer-fact")).toHaveLength(4);
    expect(screen.getByText(/12345678901234567890.12345678/)).toBeInTheDocument();
    expect(screen.getByText("99.1% observation-time coverage; 75/75 reporting servers", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("STALE / NO_DATA", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Important").parentElement).not.toHaveClass("answer-fact");
  });

  it("renders supplied tables with exact backend text", () => {
    render(<AnalystAnswer answer={'| Period | Cost |\n| --- | --- |\n| Current | USD 0.12345678 |\n| Previous | USD 0.10000000 |'} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "USD 0.12345678" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "USD 0.10000000" })).toBeInTheDocument();
  });

  it("does not execute supplied HTML or load remote images", () => {
    const { container } = render(<AnalystAnswer answer={'<script>alert("unsafe")</script>\n\n[unsafe](javascript:alert(1))\n\n![Provided image description](https://example.com/image.png)'} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("Provided image description")).toBeInTheDocument();
    expect(screen.getByText("unsafe").getAttribute("href")).not.toContain("javascript:");
  });
});
