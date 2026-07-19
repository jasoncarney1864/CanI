// Client-side upload constraints. These mirror docs-api's server-side gate
// (docs_api_app/uploads.py) so the UI can reject obviously-bad files before the round-trip.
// The server remains the source of truth (magic-byte sniffing, dedupe) — this is UX, not
// security.

export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024; // 25MB — matches docs-api MAX_UPLOAD_BYTES

// Accepted content types -> friendly extension list, mirroring docs-api _ALLOWED.
export const ACCEPTED_TYPES: Record<string, string> = {
  "application/pdf": "PDF",
  "image/jpeg": "JPEG",
  "image/png": "PNG",
  "application/zip": "ZIP",
  "application/x-zip-compressed": "ZIP", // browser alias for .zip, normalized server-side
};

/** The `accept` attribute for the file input. */
export const ACCEPT_ATTR = ".pdf,.jpg,.jpeg,.png,.zip";

/** Human-readable size, e.g. "3.2 MB". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Client-side pre-check. Returns an error string, or null if the file looks acceptable. */
export function validateFile(file: File): string | null {
  if (file.size === 0) return "That file is empty.";
  if (file.size > MAX_UPLOAD_BYTES) {
    return `That file is ${formatBytes(file.size)} — the limit is ${formatBytes(MAX_UPLOAD_BYTES)}.`;
  }
  // Browsers sometimes send an empty content type; let the server make the final call then.
  if (file.type && !(file.type in ACCEPTED_TYPES)) {
    return `${file.type || "That file type"} isn't supported. Upload a PDF, JPEG, PNG, or ZIP.`;
  }
  return null;
}
