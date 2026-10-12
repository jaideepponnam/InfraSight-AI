import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { DatabaseSample } from "../DatabaseSample";

it("keeps the fictional database reference collapsed and makes no API request", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch");
  try {
    render(<DatabaseSample />);
    const toggle = screen.getByRole("button", { name: "Sample database ? for reference" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/fictional, not live analytics/)).toBeInTheDocument();
    expect(screen.getByText("app-server-01")).toBeInTheDocument();
    expect(screen.queryByText(/raw_telemetry_id|server_id|API_ADMIN_KEY/)).not.toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  } finally { fetcher.mockRestore(); }
});
