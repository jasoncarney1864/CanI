"use client";

import { useEffect, useState } from "react";
import type {
  LegalConverseResponse,
  LegalDraft,
  LegalDraftPreview,
  LegalFieldProposal,
  LegalFieldSpec,
  LegalFinalizeResponse,
  LegalTemplateDetail,
  LegalTemplateSummary,
} from "@/lib/types";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  proposal?: LegalFieldProposal;
}

type Stage = "picker" | "drafting" | "finalized";

const SOURCE_LABEL: Record<LegalFieldProposal["source"], string> = {
  user_document: "From your documents",
  state_statute: "From the Nevada reference library",
  mixed: "From your documents + the Nevada reference library",
};

/**
 * Legal-drafting assistant (Sprint 4): template picker -> conversational field collection
 * (chat + a field panel showing filled/pending status) -> preview -> finalize -> download.
 * Every AI-proposed field value is shown with its source (own documents vs. the Nevada
 * reference library) and citations, and nothing is saved until the user explicitly
 * confirms it — either by accepting a proposal or typing/selecting a value directly.
 */
export function LegalDraftingView() {
  const [templates, setTemplates] = useState<LegalTemplateSummary[] | null>(null);
  const [templatesError, setTemplatesError] = useState<string | null>(null);

  const [stage, setStage] = useState<Stage>("picker");
  const [template, setTemplate] = useState<LegalTemplateDetail | null>(null);
  const [draft, setDraft] = useState<LegalDraft | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [activeFieldKey, setActiveFieldKey] = useState<string | null>(null);
  const [manualValues, setManualValues] = useState<Record<string, string>>({});
  const [savingField, setSavingField] = useState<string | null>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [sending, setSending] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  const [preview, setPreview] = useState<LegalDraftPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const [finalizing, setFinalizing] = useState(false);
  const [finalizeError, setFinalizeError] = useState<string | null>(null);
  const [finalizeResult, setFinalizeResult] = useState<LegalFinalizeResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/legal/templates")
      .then((res) => res.json().catch(() => ({})).then((data) => ({ ok: res.ok, data })))
      .then(({ ok, data }) => {
        if (cancelled) return;
        if (!ok) {
          setTemplatesError((data as { error?: string })?.error ?? "Couldn't load templates.");
          return;
        }
        setTemplates(data as LegalTemplateSummary[]);
      })
      .catch(() => {
        if (!cancelled) setTemplatesError("Couldn't reach the server.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function startDraft(slug: string) {
    setCreating(true);
    setCreateError(null);
    try {
      const [templateRes, draftRes] = await Promise.all([
        fetch(`/api/legal/templates/${encodeURIComponent(slug)}`),
        fetch("/api/legal/drafts", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ template_slug: slug }),
        }),
      ]);
      const templateData = await templateRes.json().catch(() => ({}));
      const draftData = await draftRes.json().catch(() => ({}));
      if (!templateRes.ok) {
        throw new Error((templateData as { error?: string })?.error ?? "Couldn't load template.");
      }
      if (!draftRes.ok) {
        throw new Error((draftData as { error?: string })?.error ?? "Couldn't start draft.");
      }
      setTemplate(templateData as LegalTemplateDetail);
      setDraft(draftData as LegalDraft);
      setStage("drafting");
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : "Couldn't start draft.");
    } finally {
      setCreating(false);
    }
  }

  async function confirmField(fieldKey: string, value: string) {
    if (!draft || !value.trim()) return;
    setSavingField(fieldKey);
    try {
      const res = await fetch(`/api/legal/drafts/${draft.legal_draft_id}/fields/confirm`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ fields: { [fieldKey]: value } }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error((data as { error?: string })?.error ?? "Couldn't save field.");
      setDraft(data as LegalDraft);
      setPreview(null); // stale now that a field changed
    } catch (e) {
      setChatError(e instanceof Error ? e.message : "Couldn't save field.");
    } finally {
      setSavingField(null);
    }
  }

  async function sendMessage() {
    if (!draft || !chatInput.trim()) return;
    const message = chatInput.trim();
    setMessages((m) => [...m, { role: "user", text: message }]);
    setChatInput("");
    setSending(true);
    setChatError(null);
    try {
      const res = await fetch(`/api/legal/drafts/${draft.legal_draft_id}/converse`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message, field_key: activeFieldKey }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error((data as { error?: string })?.error ?? "Couldn't reach the assistant.");
      const converse = data as LegalConverseResponse;
      setMessages((m) => [...m, { role: "assistant", text: converse.reply, proposal: converse.proposals[0] }]);
    } catch (e) {
      setChatError(e instanceof Error ? e.message : "Couldn't reach the assistant.");
    } finally {
      setSending(false);
    }
  }

  async function loadPreview() {
    if (!draft) return;
    setPreviewLoading(true);
    try {
      const res = await fetch(`/api/legal/drafts/${draft.legal_draft_id}/preview`);
      const data = await res.json().catch(() => ({}));
      if (res.ok) setPreview(data as LegalDraftPreview);
    } finally {
      setPreviewLoading(false);
    }
  }

  async function finalize() {
    if (!draft) return;
    setFinalizing(true);
    setFinalizeError(null);
    try {
      const res = await fetch(`/api/legal/drafts/${draft.legal_draft_id}/finalize`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error((data as { error?: string })?.error ?? "Couldn't finalize.");
      const result = data as LegalFinalizeResponse;
      setFinalizeResult(result);
      if (result.status === "finalized") setStage("finalized");
    } catch (e) {
      setFinalizeError(e instanceof Error ? e.message : "Couldn't finalize.");
    } finally {
      setFinalizing(false);
    }
  }

  if (stage === "picker") {
    return (
      <div className="legal-draft">
        <h2 className="legal-draft__title">Draft a legal document</h2>
        {templatesError && <p className="legal-draft__error">{templatesError}</p>}
        {templates === null && !templatesError && <p>Loading templates…</p>}
        {templates?.length === 0 && <p>No templates are available yet.</p>}
        <ul className="legal-draft__template-list">
          {templates?.map((t) => (
            <li key={t.slug} className="legal-draft__template-card">
              <h3>{t.title}</h3>
              <p className="legal-draft__jurisdiction-note">{t.jurisdiction_note}</p>
              <p className="legal-draft__disclaimer">{t.disclaimer_text}</p>
              <button type="button" disabled={creating} onClick={() => void startDraft(t.slug)}>
                {creating ? "Starting…" : "Start drafting"}
              </button>
            </li>
          ))}
        </ul>
        {createError && <p className="legal-draft__error">{createError}</p>}
      </div>
    );
  }

  if (stage === "finalized" && finalizeResult?.document_id) {
    return (
      <div className="legal-draft">
        <h2 className="legal-draft__title">{template?.title} — finalized</h2>
        <p>Your document has been generated and saved to your Documents page.</p>
        <a
          className="legal-draft__download"
          href={`/api/documents/${finalizeResult.document_id}/original`}
          download
        >
          Download PDF
        </a>
      </div>
    );
  }

  if (!draft || !template) return null;

  const fieldEntries = Object.entries(template.field_schema);
  const filledCount = fieldEntries.filter(([key]) => !!draft.field_values_json[key]).length;
  const activeSpec = activeFieldKey ? template.field_schema[activeFieldKey] : null;

  return (
    <div className="legal-draft legal-draft--drafting">
      <aside className="legal-draft__fields">
        <h3>{template.title}</h3>
        <p className="legal-draft__progress">
          {filledCount} of {fieldEntries.length} fields filled
        </p>
        <ul>
          {fieldEntries.map(([key, spec]) => {
            const value = draft.field_values_json[key];
            const isActive = activeFieldKey === key;
            return (
              <li
                key={key}
                className={`legal-draft__field${value ? " legal-draft__field--filled" : ""}${isActive ? " legal-draft__field--active" : ""}`}
              >
                <button type="button" className="legal-draft__field-select" onClick={() => setActiveFieldKey(key)}>
                  <span className="legal-draft__field-status" aria-hidden>
                    {value ? "✓" : "○"}
                  </span>
                  {spec.label}
                  {spec.required && !value ? " *" : ""}
                </button>
                {value && <p className="legal-draft__field-value">{value}</p>}
                {isActive && (
                  <FieldEditor
                    spec={spec}
                    value={manualValues[key] ?? value ?? ""}
                    saving={savingField === key}
                    onChange={(v) => setManualValues((m) => ({ ...m, [key]: v }))}
                    onSave={(v) => void confirmField(key, v)}
                  />
                )}
              </li>
            );
          })}
        </ul>
        <div className="legal-draft__actions">
          <button type="button" onClick={() => void loadPreview()} disabled={previewLoading}>
            {previewLoading ? "Loading preview…" : "Preview"}
          </button>
          <button type="button" onClick={() => void finalize()} disabled={finalizing}>
            {finalizing ? "Finalizing…" : "Finalize & generate PDF"}
          </button>
        </div>
        {finalizeError && <p className="legal-draft__error">{finalizeError}</p>}
        {finalizeResult?.status === "finalize_pending" && (
          <p className="legal-draft__hint">Still finalizing — try again in a moment.</p>
        )}
      </aside>

      <section className="legal-draft__chat">
        {activeSpec && (
          <p className="legal-draft__active-field">
            Asking about: <strong>{activeSpec.label}</strong>
            {activeSpec.help && ` — ${activeSpec.help}`}
          </p>
        )}
        <div className="legal-draft__messages">
          {messages.map((m, i) => (
            <div key={i} className={`legal-draft__message legal-draft__message--${m.role}`}>
              <p>{m.text}</p>
              {m.proposal && (
                <div className={`legal-draft__proposal legal-draft__proposal--${m.proposal.source}`}>
                  <span className="legal-draft__source-badge">{SOURCE_LABEL[m.proposal.source]}</span>
                  <p className="legal-draft__proposal-value">{m.proposal.value}</p>
                  <ul className="legal-draft__citations">
                    {m.proposal.citations.map((c, ci) => (
                      <li key={ci}>
                        {c.source_kind === "user_document" ? c.document_title : c.citation_ref}
                        {c.snippet && (
                          <span className="legal-draft__citation-snippet"> — &ldquo;{c.snippet}&rdquo;</span>
                        )}
                      </li>
                    ))}
                  </ul>
                  <button type="button" onClick={() => void confirmField(m.proposal!.field_key, m.proposal!.value)}>
                    Use this value
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
        {chatError && <p className="legal-draft__error">{chatError}</p>}
        <form
          className="legal-draft__composer"
          onSubmit={(e) => {
            e.preventDefault();
            void sendMessage();
          }}
        >
          <input
            type="text"
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            placeholder={activeSpec ? `Ask about ${activeSpec.label}…` : "Ask a question…"}
            disabled={sending}
          />
          <button type="submit" disabled={sending || !chatInput.trim()}>
            {sending ? "Thinking…" : "Send"}
          </button>
        </form>
      </section>

      {preview && (
        <div className="legal-draft__preview-overlay" role="dialog" aria-label="Draft preview">
          <div className="legal-draft__preview-panel">
            <button type="button" className="legal-draft__preview-close" onClick={() => setPreview(null)}>
              Close
            </button>
            {preview.missing_required_fields.length > 0 && (
              <p className="legal-draft__hint">
                Missing required fields:{" "}
                {preview.missing_required_fields.map((k) => template.field_schema[k]?.label ?? k).join(", ")}
              </p>
            )}
            <pre className="legal-draft__preview-body">{preview.body}</pre>
            <p className="legal-draft__disclaimer">{preview.disclaimer_text}</p>
          </div>
        </div>
      )}
    </div>
  );
}

function FieldEditor({
  spec,
  value,
  saving,
  onChange,
  onSave,
}: {
  spec: LegalFieldSpec;
  value: string;
  saving: boolean;
  onChange: (v: string) => void;
  onSave: (v: string) => void;
}) {
  return (
    <div className="legal-draft__field-editor">
      {spec.help && <p className="legal-draft__field-help">{spec.help}</p>}
      {spec.type === "textarea" ? (
        <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={3} />
      ) : spec.type === "select" ? (
        <select value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">Choose…</option>
          {spec.options?.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      ) : spec.type === "multiselect" ? (
        <div className="legal-draft__multiselect">
          {spec.options?.map((o) => {
            const selected = value
              .split(";")
              .map((s) => s.trim())
              .filter(Boolean);
            const checked = selected.includes(o);
            return (
              <label key={o}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => {
                    const next = checked ? selected.filter((s) => s !== o) : [...selected, o];
                    onChange(next.join("; "));
                  }}
                />
                {o}
              </label>
            );
          })}
        </div>
      ) : spec.type === "date" ? (
        <input type="date" value={value} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input type="text" value={value} onChange={(e) => onChange(e.target.value)} />
      )}
      <button type="button" disabled={saving || !value.trim()} onClick={() => onSave(value)}>
        {saving ? "Saving…" : "Save"}
      </button>
    </div>
  );
}
