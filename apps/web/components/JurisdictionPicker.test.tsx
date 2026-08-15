import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { JurisdictionPicker } from "./JurisdictionPicker";

describe("JurisdictionPicker (docs/20 §20.8 Q2 store-picker)", () => {
  it("renders the Nevada-only option, selected", () => {
    render(<JurisdictionPicker value="us-nv" onChange={() => {}} />);
    const select = screen.getByLabelText("State") as HTMLSelectElement;
    expect(select.value).toBe("us-nv");
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.getByRole("option", { name: "Nevada" })).toBeInTheDocument();
  });

  it("calls onChange with the newly selected slug", () => {
    const onChange = vi.fn();
    render(<JurisdictionPicker value="us-nv" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("State"), { target: { value: "us-nv" } });
    expect(onChange).toHaveBeenCalledWith("us-nv");
  });
});
