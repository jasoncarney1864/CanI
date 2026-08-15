import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AvatarStage } from "./AvatarStage";

describe("AvatarStage", () => {
  it("shows the opt-in toggle and no video tile while inactive", () => {
    render(
      <AvatarStage state="inactive" error={null} isStreamReady={false} attach={vi.fn()} onToggle={vi.fn()} />,
    );

    expect(screen.getByRole("button", { name: "Show talking avatar" })).toBeInTheDocument();
    expect(screen.queryByLabelText("LiveAvatar talking avatar")).not.toBeInTheDocument();
  });

  it("calls onToggle when the button is clicked", () => {
    const onToggle = vi.fn();
    render(
      <AvatarStage state="inactive" error={null} isStreamReady={false} attach={vi.fn()} onToggle={onToggle} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Show talking avatar" }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("disables the toggle while connecting, without a video tile yet", () => {
    render(
      <AvatarStage state="connecting" error={null} isStreamReady={false} attach={vi.fn()} onToggle={vi.fn()} />,
    );

    expect(screen.getByRole("button", { name: "Connecting…" })).toBeDisabled();
  });

  it("renders the video tile once connected and offers Hide avatar", () => {
    render(
      <AvatarStage state="connected" error={null} isStreamReady={false} attach={vi.fn()} onToggle={vi.fn()} />,
    );

    expect(screen.getByRole("button", { name: "Hide avatar" })).toBeInTheDocument();
    expect(screen.getByLabelText("LiveAvatar talking avatar")).toBeInTheDocument();
    expect(screen.getByText("Connecting…")).toBeInTheDocument(); // stream not ready yet
  });

  it("calls attach once the stream is ready", () => {
    const attach = vi.fn();
    render(
      <AvatarStage state="connected" error={null} isStreamReady={true} attach={attach} onToggle={vi.fn()} />,
    );

    expect(attach).toHaveBeenCalledTimes(1);
    expect(attach.mock.calls[0][0]).toBeInstanceOf(HTMLVideoElement);
  });

  it("surfaces an error message without blocking the toggle", () => {
    render(
      <AvatarStage
        state="error"
        error="The talking avatar isn't set up on this deployment."
        isStreamReady={false}
        attach={vi.fn()}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("isn't set up on this deployment");
    expect(screen.getByRole("button", { name: "Show talking avatar" })).toBeEnabled();
  });
});
