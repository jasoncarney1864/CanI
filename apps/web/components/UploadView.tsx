"use client";

import { useRef, useState } from "react";
import { ACCEPT_ATTR, formatBytes, validateFile } from "@/lib/uploads";

interface UploadViewProps {
  /** Jump to the Documents view (e.g. after a successful upload) to watch ingestion. */
  onGoToDocuments: () => void;
  /**
   * Backend spoke value ("General" | "Legal" | "Health" | "Finance") to preselect in the
   * category dropdown. Without this the picker always defaulted to "General" regardless of
   * which spoke tab the user was on, and since choosing/dropping a file uploads immediately
   * (no confirm step), a user who dropped a file before touching the dropdown silently
   * uploaded into the wrong spoke. Defaulting to the active tab removes that footgun; the
   * dropdown remains editable for the deliberate cross-spoke-upload case.
   */
  initialSpoke?: string;
}

type UploadState =
  | { kind: "idle" }
  | { kind: "uploading"; name: string }
  | { kind: "done"; name: string; status: string; deduplicated: boolean }
  | { kind: "error"; message: string };

/**
 * Upload view (A3). A file picker + drag-and-drop that posts to the owner-scoped
 * /api/documents proxy. Client-side type/size validation mirrors docs-api; the server
 * remains the source of truth. On success, points the user at Documents to watch ingestion.
 */
export function UploadView({ onGoToDocuments, initialSpoke = "General" }: UploadViewProps) {
  const [state, setState] = useState<UploadState>({ kind: "idle" });
  const [dragging, setDragging] = useState(false);
  const [spoke, setSpoke] = useState<string>(initialSpoke);
  const inputRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    const localError = validateFile(file);
    if (localError) {
      setState({ kind: "error", message: localError });
      return;
    }
    setState({ kind: "uploading", name: file.name });
    try {
      const form = new FormData();
      form.append("file", file, file.name);
      form.append("spoke", spoke);
      const res = await fetch("/api/documents", { method: "POST", body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data?.error ?? `Upload failed (${res.status}).`);
      }
      // A "" version id means docs-api deduplicated against an existing upload.
      const deduplicated = !data.document_version_id;
      setState({ kind: "done", name: file.name, status: data.status ?? "queued", deduplicated });
    } catch (e) {
      setState({ kind: "error", message: e instanceof Error ? e.message : "Upload failed." });
    }
  }

  function onDrop(event: React.DragEvent) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) void upload(file);
  }

  return (
    <div className="uploadview">
      <p className="col-label">Upload</p>
      <h2 className="uploadview__title">Add a document</h2>
      <p className="uploadview__lead">
        PDF, JPEG, PNG, or a ZIP of several files. Up to {formatBytes(25 * 1024 * 1024)}. Once
        it&rsquo;s indexed you can ask questions about it.
      </p>

      <div className="uploadview__spoke-selector">
        <label htmlFor="spoke-select">Category:</label>
        <select
          id="spoke-select"
          value={spoke}
          onChange={(e) => setSpoke(e.target.value)}
          className="uploadview__spoke-select"
        >
          <option value="General">General</option>
          <option value="Legal">Legal</option>
          <option value="Health">Health</option>
          <option value="Finance">Finance</option>
        </select>
      </div>

      <div
        className={`dropzone${dragging ? " dropzone--active" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
        aria-label="Choose a file to upload"
      >
        <span className="dropzone__glyph" aria-hidden>
          &#8593;
        </span>
        <span className="dropzone__prompt">
          <strong>Choose a file</strong> or drag it here
        </span>
        <input
          ref={inputRef}
          className="dropzone__input"
          type="file"
          accept={ACCEPT_ATTR}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void upload(file);
            e.target.value = ""; // allow re-selecting the same file
          }}
        />
      </div>

      {state.kind === "uploading" && (
        <p className="uploadview__status" role="status">
          Uploading <strong>{state.name}</strong>&hellip;
        </p>
      )}
      {state.kind === "done" && (
        <div className="uploadview__result" role="status">
          <p>
            <strong>{state.name}</strong>{" "}
            {state.deduplicated
              ? "is already in your library."
              : `uploaded — now ${state.status}.`}
          </p>
          <button type="button" className="uploadview__cta" onClick={onGoToDocuments}>
            View in Documents &rarr;
          </button>
        </div>
      )}
      {state.kind === "error" && (
        <p className="uploadview__error" role="alert">
          {state.message}
        </p>
      )}
    </div>
  );
}
