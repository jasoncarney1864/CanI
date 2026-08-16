import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AvatarStage } from "./AvatarStage";
import type { AvatarState } from "@/lib/useLiveAvatar";

// Shared base props so each test only overrides what it actually cares about.
function baseProps(overrides: Partial<React.ComponentProps<typeof AvatarStage>> = {}) {
  return {
    state: "inactive" as AvatarState,
    error: null,
    isStreamReady: false,
    isSpeaking: false,
    attach: vi.fn(),
    onToggle: vi.fn(),
    onInterrupt: vi.fn(),
    ...overrides,
  };
}

describe("AvatarStage", () => {
  it("shows the opt-in toggle and no video tile while inactive", () => {
    render(<AvatarStage {...baseProps()} />);

    expect(screen.getByRole("button", { name: "Show talking avatar" })).toBeInTheDocument();
    expect(screen.queryByLabelText("LiveAvatar talking avatar")).not.toBeInTheDocument();
  });

  it("calls onToggle when the button is clicked", () => {
    const onToggle = vi.fn();
    render(<AvatarStage {...baseProps({ onToggle })} />);

    fireEvent.click(screen.getByRole("button", { name: "Show talking avatar" }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("disables the toggle while connecting, without a video tile yet", () => {
    render(<AvatarStage {...baseProps({ state: "connecting" })} />);

    expect(screen.getByRole("button", { name: "Connecting…" })).toBeDisabled();
  });

  it("renders the video tile once connected and offers Hide avatar", () => {
    render(<AvatarStage {...baseProps({ state: "connected" })} />);

    expect(screen.getByRole("button", { name: "Hide avatar" })).toBeInTheDocument();
    expect(screen.getByLabelText("LiveAvatar talking avatar")).toBeInTheDocument();
    expect(screen.getByText("Connecting…")).toBeInTheDocument(); // stream not ready yet
  });

  it("calls attach once the stream is ready, targeting the (hidden) video element", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const attach = vi.fn();
    render(<AvatarStage {...baseProps({ state: "connected", isStreamReady: true, attach })} />);

    expect(attach).toHaveBeenCalledTimes(1);
    expect(attach.mock.calls[0][0]).toBeInstanceOf(HTMLVideoElement);

    vi.restoreAllMocks();
  });

  it("renders a chroma-keyed canvas as the visible surface, not the raw video, once connected", () => {
    // jsdom has no real canvas support (getContext("2d") logs a noisy "not implemented"
    // warning and returns null) — stub it so this test's intent (DOM structure) isn't
    // drowned out by that; the component's handling of a null context is covered below.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);

    render(<AvatarStage {...baseProps({ state: "connected", isStreamReady: true })} />);

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
      render(<AvatarStage {...baseProps({ state: "connected", isStreamReady: true })} />),
    ).not.toThrow();
  });

  it("surfaces an error message without blocking the toggle", () => {
    render(
      <AvatarStage
        {...baseProps({ state: "error", error: "The talking avatar isn't set up on this deployment." })}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("isn't set up on this deployment");
    expect(screen.getByRole("button", { name: "Show talking avatar" })).toBeEnabled();
  });

  describe("Stop talking (interrupt) control", () => {
    // These all use isStreamReady: true, which drives AvatarStage's chroma-key canvas
    // effect — jsdom has no real getContext("2d"), so stub it to keep output clean; the
    // null-context path itself is already covered above.
    beforeEach(() => {
      vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    });
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("does not render while the stream is still connecting (not ready yet)", () => {
      render(<AvatarStage {...baseProps({ state: "connected", isStreamReady: false, isSpeaking: true })} />);

      expect(screen.queryByRole("button", { name: "Stop talking" })).not.toBeInTheDocument();
    });

    it("does not render once ready but not currently speaking", () => {
      render(<AvatarStage {...baseProps({ state: "connected", isStreamReady: true, isSpeaking: false })} />);

      expect(screen.queryByRole("button", { name: "Stop talking" })).not.toBeInTheDocument();
    });

    it("renders once the stream is ready and the avatar is speaking", () => {
      render(<AvatarStage {...baseProps({ state: "connected", isStreamReady: true, isSpeaking: true })} />);

      expect(screen.getByRole("button", { name: "Stop talking" })).toBeInTheDocument();
      // Distinct from the session-ending toggle, which must still say "Hide avatar".
      expect(screen.getByRole("button", { name: "Hide avatar" })).toBeInTheDocument();
    });

    it("calls onInterrupt (not onToggle) when clicked", () => {
      const onInterrupt = vi.fn();
      const onToggle = vi.fn();
      render(
        <AvatarStage
          {...baseProps({ state: "connected", isStreamReady: true, isSpeaking: true, onInterrupt, onToggle })}
        />,
      );

      fireEvent.click(screen.getByRole("button", { name: "Stop talking" }));
      expect(onInterrupt).toHaveBeenCalledTimes(1);
      expect(onToggle).not.toHaveBeenCalled();
    });
  });
});
