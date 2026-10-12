import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { HealthPanel } from "../HealthPanel";
import { APIClient, snapshot } from "../api";
import type { Overview } from "../types";
const data = { inventory_servers:75, healthy_servers:0,warning_servers:0,critical_servers:0,stale_servers:75,no_data_servers:0 } as Overview;

it("has exactly Live and Avg, fetching duration-weighted percentages only when selected", async () => {
  const client = new APIClient();
  const avg = vi.spyOn(client,"averageHealth").mockResolvedValue({ data:[{scope_kind:"fleet",source_id:null,region_code:null,observation_count:10,healthy_fraction:"0.75",warning_fraction:"0.25",critical_fraction:"0",coverage_fraction:"0.1",health_overlap_detected:false}],meta:{request_id:"x"} });
  render(<HealthPanel client={client} context={snapshot()} data={data} regions={[]} />);
  const control=screen.getByLabelText("Health view");
  expect(screen.getAllByRole("option").map(o=>o.textContent)).toEqual(["Live","Avg"]);
  expect(screen.getByText("STALE")).toBeInTheDocument();
  expect(avg).not.toHaveBeenCalled();
  await userEvent.selectOptions(control,"Avg");
  await screen.findByText("75.0%");
  expect(screen.getByText("25.0%")).toBeInTheDocument();
  expect(screen.getByText(/Missing time is not counted as healthy/)).toBeInTheDocument();
  expect(screen.queryByText("STALE")).not.toBeInTheDocument();
  await userEvent.selectOptions(control,"Live");
  expect(screen.getByText("STALE")).toBeInTheDocument();
});

it("shows missing data instead of a healthy average", async () => {
  const client=new APIClient();
  vi.spyOn(client,"averageHealth").mockResolvedValue({data:[{scope_kind:"fleet",source_id:null,region_code:null,observation_count:0,healthy_fraction:null,warning_fraction:null,critical_fraction:null,coverage_fraction:"0",health_overlap_detected:false}],meta:{request_id:"x"}});
  render(<HealthPanel client={client} context={snapshot()} data={data} regions={[]} />);
  await userEvent.selectOptions(screen.getByLabelText("Health view"),"Avg");
  await screen.findByText("No recorded telemetry in this window.");
  expect(screen.queryByText("100.0%")).not.toBeInTheDocument();
});

it("shows a safe error while keeping Live available", async () => {
  const client=new APIClient();
  vi.spyOn(client,"averageHealth").mockRejectedValue(new Error("private-error"));
  render(<HealthPanel client={client} context={snapshot()} data={data} regions={[]} />);
  await userEvent.selectOptions(screen.getByLabelText("Health view"),"Avg");
  await screen.findByText("Average health unavailable");
  expect(screen.queryByText("private-error")).not.toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("Health view"),"Live");
  expect(screen.getByText("STALE")).toBeInTheDocument();
});
