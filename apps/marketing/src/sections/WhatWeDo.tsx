const CAPABILITIES = [
  {
    key: "legal",
    title: "Legal",
    description:
      "Leases, contracts, HOA covenants, and filings. Ask \u201cCan I sublet?\u201d and get a plain-English answer with the exact clause spotlighted \u2014 not thirty pages of legalese.",
  },
  {
    key: "health",
    title: "Health",
    description:
      "Health records and benefits documents. Understand what your plan actually covers and what your records actually say, with the source passage alongside every answer.",
  },
  {
    key: "finance",
    title: "Finance",
    description:
      "Tax notices, loan agreements, and statements. Get a clear read on the terms you agreed to and the deadlines that matter, cited line by line.",
  },
] as const;

export function WhatWeDo() {
  return (
    <section id="what-we-do" className="section">
      <div className="section-inner">
        <h2>One hub. A spoke for each part of your life.</h2>
        <p className="section-lede">
          CanI is a hub-and-spoke platform: one place to sign in and upload, with
          dedicated workspaces for the paperwork that runs your life. Three spokes today
          &mdash; more to come.
        </p>
        <div className="capability-grid">
          {CAPABILITIES.map((capability) => (
            <div
              className={`capability-card capability-card--${capability.key}`}
              key={capability.key}
            >
              <h3>{capability.title}</h3>
              <p>{capability.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
