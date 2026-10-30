import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AppHeader } from "../AppHeader";
import App from "../App";
import { APIClient } from "../api";

beforeEach(() => vi.spyOn(APIClient.prototype, "latestSuccessfulRun").mockResolvedValue(null));
afterEach(() => vi.restoreAllMocks());

it("preserves legacy destinations and their reference date/time alongside SRE navigation", async () => {
  const navigate = vi.fn(); const refresh = vi.fn();
  render(<AppHeader page="Overview" referenceTime="2026-10-12T09:37:52Z" busy={false} onNavigate={navigate} onRefresh={refresh} />);
  expect(screen.getByText("LIVE")).toBeInTheDocument();
  expect(screen.getByText("Oct 12, 2026")).toBeInTheDocument();
  expect(screen.getByText("3:37:52 AM CST")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Overview" })).toHaveAttribute("aria-current", "page");
  await userEvent.click(screen.getByRole("button", { name: "Scout" }));
  expect(navigate).toHaveBeenCalledWith("AI Analyst");
  await userEvent.click(screen.getByRole("button", { name: "Refresh analytics" }));
  expect(refresh).toHaveBeenCalledTimes(1);
  expect(screen.queryByLabelText("Reference mode")).not.toBeInTheDocument();
  expect(screen.queryByText("SOURCE")).not.toBeInTheDocument();
  expect(screen.queryByText("API connected")).not.toBeInTheDocument();
  expect(screen.queryByText("CONTROLLED ANALYTICS")).not.toBeInTheDocument();
});

it("disables refresh while data is loading", () => {
  render(<AppHeader page="Pipeline" referenceTime="2026-10-12T09:37:52Z" busy onNavigate={vi.fn()} onRefresh={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Refresh analytics" })).toBeDisabled();
});

it("starts the application in current Live mode instead of the historical snapshot", async () => {
  const overview = vi.spyOn(APIClient.prototype, "overview").mockRejectedValue(new Error("unavailable"));
  vi.spyOn(APIClient.prototype, "regions").mockResolvedValue({data:[],meta:{request_id:"test"}});
  const now = Date.now();
  const { container } = render(<App />);
  await waitFor(() => expect(overview).toHaveBeenCalled());
  expect(overview.mock.calls[0][0].mode).toBe("LIVE");
  expect(Math.abs(Date.parse(overview.mock.calls[0][0].reference_time)-now)).toBeLessThan(1000);
  expect(container.querySelector(".navigation")).toBeNull();
  expect(container.querySelector(".snapshot-note")).toBeNull();
});


it("hides telemetry and retrieval metadata on Scout while keeping the real request context", async () => {
  vi.spyOn(APIClient.prototype, "overview").mockRejectedValue(new Error("unavailable"));
  vi.spyOn(APIClient.prototype, "regions").mockResolvedValue({data:[],meta:{request_id:"test"}});
  const { container } = render(<App />);
  await userEvent.click(screen.getByRole("button", { name: "Scout" }));
  await screen.findByRole("heading", { name: "Scout" });
  expect(container.querySelector(".scope-card")).toBeNull();
  expect(container.querySelector(".workspace-footer")).toBeNull();
  expect(screen.queryByText("Your investigation")).not.toBeInTheDocument();
});


it("uses a text wordmark and text-only navigation without destination icons", () => {
  const { container } = render(<AppHeader page="Overview" referenceTime="2026-10-12T09:37:52Z" busy={false} onNavigate={vi.fn()} onRefresh={vi.fn()} />);
  expect(screen.getByRole("link", { name: "InfraSight AI - Overview" })).toHaveTextContent("InfraSight AI");
  expect(container.querySelectorAll(".top-navigation svg")).toHaveLength(0);
  expect(container.querySelector(".brand svg")).toBeNull();
});
