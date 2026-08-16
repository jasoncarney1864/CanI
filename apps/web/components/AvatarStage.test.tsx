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

  it("calls attach once the stream is ready, targeting the (hidden) video element", () => {
    const attach = vi.fn();
    render(
      <AvatarStage state="connected" error={null} isStreamReady={true} attach={attach} onToggle={vi.fn()} />,
    );

    expect(attach).toHaveBeenCalledTimes(1);
    expect(attach.mock.calls[0][0]).toBeInstanceOf(HTMLVideoElement);
  });

  it("renders a chroma-keyed canvas as the visible surface, not the raw video, once connected", () => {
    // jsdom has no real canvas support (getContext("2d") logs a noisy "not implemented"
    // warning and returns null) — stub it so this test's intent (DOM structure) isn't
    // drowned out by that; the component's handling of a null context is covered below.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);

    render(
      <AvatarStage state="connected" error={null} isStreamReady={true} attach={vi.fn()} onToggle={vi.fn()} />,
    );

    // The canvas — not the video — now carries the accessible label, since it's what's
    // actually rendered to the user; the video is the SDK's off-screen attach target.
    const canvas = screen.getByLabelText("LiveAvatar talking avatar");
    expect(canvas.tagName).toBe("CANVAS");
    expect(canvas).toHaveAttribute("role", "img");

    const video = document.querySelector("video");
    expect(video).not.toBeNull();
    expect(video).toHaveAttribute("aria-hidden", "true");
    expect(video).not.toHaveAttribute("aria-label");

    vi.restoreAllMocks();
  });

  it("does not throw when the canvas 2D context is unavailable (jsdom's actual behavior)", () => {
    // Unlike the test above, this one deliberately exercises the *real* jsdom
    // getContext("2d") -> null path (no stub) to prove the component's defensive bail-out
    // actually works against the environment's real behavior, not just an assumed mock.
    expect(() =>
      render(
        <AvatarStage state="connected" error={null} isStreamReady={true} attach={vi.fn()} onToggle={vi.fn()} />,
      ),
    ).not.toThrow();
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
