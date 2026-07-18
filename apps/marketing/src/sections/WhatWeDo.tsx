const CAPABILITIES = [
  {
    title: "Statute & case law research",
    description:
      "Search across Nevada statutes and case law at once, and get back the passages that actually answer your question — not just a list of documents to open.",
  },
  {
    title: "Citation extraction",
    description:
      "Every answer comes with the specific statute sections and case citations it's drawn from, ready to verify or drop straight into a memo.",
  },
  {
    title: "Legal document analysis",
    description:
      "Upload a brief, contract, or filing and get a structured read on the relevant authority and language it references.",
  },
] as const;

export function WhatWeDo() {
  return (
    <section id="what-we-do" className="section">
      <div className="section-inner">
        <h2>What Sondra Keys does</h2>
        <p className="section-lede">
          One platform for the research work that eats the most billable
          hours: finding the right authority, extracting the citation, and
          understanding what a document actually says.
        </p>
        <div className="capability-grid">
          {CAPABILITIES.map((capability) => (
            <div className="capability-card" key={capability.title}>
              <h3>{capability.title}</h3>
              <p>{capability.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
