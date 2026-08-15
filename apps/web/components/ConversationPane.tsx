"use client";

import { useCallback, useRef } from "react";
import type { RetrievalAnswer } from "@/lib/types";
import type { Spoke } from "@/lib/spokes";
import { useVoiceConversation, type VoiceState } from "@/lib/useVoiceConversation";
import { useLiveAvatar } from "@/lib/useLiveAvatar";
import { VerdictBadge } from "./VerdictBadge";
import { LawCitationCard } from "./LawCitationCard";
import { AvatarStage } from "./AvatarStage";

interface ConversationPaneProps {
  answer: RetrievalAnswer | null;
  spoke: Spoke;
  loading: boolean;
  error: string | null;
  /** Ask a question; resolves with the answer so it can be spoken aloud. */
  onAsk: (question: string) => Promise<RetrievalAnswer | null>;
  /** The document currently open in the viewer (drives the active citation state). */
  activeDocumentId: string | null;
  /** Open a cited document in the viewer with its cited passages spotlighted. */
  onSelectCitation: (documentId: string) => void;
}

const STATUS_COPY: Record<VoiceState, { title: string; hint: string }> = {
  off: {
    title: "Tap to start a conversation",
    hint: "Speak naturally — pause when you're done and I'll answer.",
  },
  listening: { title: "Listening\u2026", hint: "Pause when you're done. Tap to end the conversation." },
  thinking: { title: "Checking your documents\u2026", hint: "" },
  speaking: { title: "Here's what I found", hint: "I'll listen again when I finish." },
  unsupported: { title: "Voice isn't available in this browser", hint: "You can still type below." },
};

/**
 * The conversation — now the whole workspace. Voice-first: a single presence
 * orb runs a hands-free listen -> answer -> listen loop. The verdict and
 * summary are the glanceable canvas while the answer is spoken aloud; compact
 * citation cards open the source in a slide-over. Typing is the quiet
 * fallback, not the primary act.
 */
export function ConversationPane({
  answer,
  spoke,
  loading,
  error,
  onAsk,
  activeDocumentId,
  onSelectCitation,
}: ConversationPaneProps) {
  // Stable indirection so the voice hook's callback always sees fresh handlers.
  const askRef = useRef(onAsk);
  askRef.current = onAsk;
  const speakRef = useRef<(text: string) => void>(() => {});

  const handleUtterance = useCallback(async (text: string) => {
    const result = await askRef.current(text);
    if (result) {
      const spoken = (result.verdict ? `${result.verdict.label}. ${result.answer}` : result.answer).replace(/\[chunk:\d+\]/g, '');
      speakRef.current(spoken);
    } else {
      speakRef.current("Sorry, I couldn't get an answer to that. Ask again whenever you're ready.");
    }
  }, []);

  const avatar = useLiveAvatar();
  const avatarSpeak = avatar.state === "connected" ? avatar.speak : undefined;
  const voice = useVoiceConversation({ onUtterance: handleUtterance, avatarSpeak });
  speakRef.current = voice.speak;

  const voiceActive = voice.state !== "off" && voice.state !== "unsupported";
  const status = STATUS_COPY[voice.state];

  function handleOrbClick() {
    if (voice.state === "unsupported") return;
    if (voiceActive) voice.stop();
    else voice.start();
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem("question") as HTMLInputElement | null;
    const question = input?.value.trim();
    if (!question || loading) return;
    if (input) input.value = "";
    voice.interject(); // pause listening while we answer a typed question
    const result = await onAsk(question);
    if (result && voiceActive) {
      const spoken = (result.verdict ? `${result.verdict.label}. ${result.answer}` : result.answer).replace(/\[chunk:\d+\]/g, '');
      voice.speak(spoken);
    }
  }

  return (
    <section className="conversation" aria-label="Conversation">
      <p className="col-label">Conversation</p>

      {answer?.verdict && <VerdictBadge verdict={answer.verdict} />}

      <div className="conversation__body">
        {error ? (
          <p className="conversation__error" role="alert">
            {error}
          </p>
        ) : (
          <p className="conversation__summary" aria-busy={loading}>
            {loading
              ? "Checking your documents\u2026"
              : (answer?.answer ??
                "Start talking about your documents — I'll answer out loud, and you can open any cited source to see the evidence spotlighted.")}
          </p>
        )}

        {!loading &&
          !error &&
          answer?.citations.map((c) =>
            c.source_kind === "user_document" ? (
              <button
                type="button"
                className={`citation-card${
                  c.document_id === activeDocumentId ? " citation-card--active" : ""
                }`}
                key={c.chunk_id}
                onClick={() => onSelectCitation(c.document_id)}
                aria-label={`Open ${c.document_title} with the cited passage spotlighted`}
              >
                <span className="citation-card__title">{c.document_title}</span>
                <span className="citation-card__loc">
                  {c.section_label} &middot; p.{c.page_start}
                </span>
              </button>
            ) : (
              <LawCitationCard citation={c} key={c.chunk_id} />
            ),
          )}
      </div>

      <AvatarStage
        state={avatar.state}
        error={avatar.error}
        isStreamReady={avatar.isStreamReady}
        attach={avatar.attach}
        onToggle={avatar.state === "connected" ? avatar.stop : avatar.start}
      />

      <div className="presence" data-state={voice.state}>
        <button
          type="button"
          className="presence__orb"
          onClick={handleOrbClick}
          disabled={voice.state === "unsupported"}
          aria-pressed={voiceActive}
          aria-label={voiceActive ? "End conversation" : "Start conversation"}
        >
          <span className="presence__ring" aria-hidden />
          <span className="presence__ring presence__ring--outer" aria-hidden />
          <span className="presence__core" aria-hidden>
            {voice.state === "speaking" ? (
              <span className="presence__bars">
                <i />
                <i />
                <i />
                <i />
              </span>
            ) : (
              "\u25CF"
            )}
          </span>
        </button>
        <p className="presence__status" role="status">
          {(voice.state === "listening" || voice.state === "thinking") && voice.transcript ? (
            <span className="presence__transcript">&ldquo;{voice.transcript}&rdquo;</span>
          ) : (
            status.title
          )}
        </p>
        {voice.error ? (
          <p className="presence__error" role="alert">
            {voice.error}
          </p>
        ) : (
          status.hint && <p className="presence__hint">{status.hint}</p>
        )}
      </div>

      <form className="ask" onSubmit={handleSubmit}>
        <input
          className="ask__input"
          type="text"
          name="question"
          placeholder={
            voice.state === "unsupported" ? spoke.placeholder : "Prefer to type? Ask here\u2026"
          }
          aria-label="Type a question instead"
          disabled={loading}
          autoComplete="off"
        />
      </form>
    </section>
  );
}
