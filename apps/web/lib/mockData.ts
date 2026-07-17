// Mock data for the prototype — the Oakwood HOA example from the design language
// blueprint (§5). No live API is called; these shapes mirror the real contracts.

import type { RetrievalAnswer, SourceDocument } from "./types";

export const mockAnswer: RetrievalAnswer = {
  verdict: {
    kind: "yes_with_conditions",
    label: "Yes, with conditions",
  },
  answer:
    "According to the Oakwood HOA Covenants, you are permitted to build this " +
    "structure. Your proposed dimensions fall under the 10x10 foot (100 sq ft) " +
    "maximum \u2014 provided the shed sits in the rear yard and, if built from " +
    "aluminum or steel, is painted to match your primary residence.",
  citations: [
    {
      document_id: "doc-oakwood-hoa",
      document_title: "Oakwood HOA Covenants",
      page_start: 7,
      page_end: 7,
      section_label: "Section 7: Outbuildings",
      chunk_id: "chunk-7c",
      snippet:
        "C. Material restrictions: Aluminum and steel structures are permitted " +
        "but must be painted to match the primary residence.",
    },
  ],
  insufficient_evidence: false,
};

export const mockDocument: SourceDocument = {
  title: "Oakwood HOA Covenants",
  section_label: "Section 7: Outbuildings",
  highlightChunkId: "chunk-7c",
  paragraphs: [
    { id: "chunk-7a", text: "A. No temporary structures are permitted." },
    {
      id: "chunk-7b",
      text:
        "B. Freestanding storage sheds are permitted in rear yards only, " +
        "provided they do not exceed 100 square feet.",
    },
    {
      id: "chunk-7c",
      text:
        "C. Material restrictions: Aluminum and steel structures are permitted " +
        "but must be painted to match the primary residence.",
    },
  ],
};
