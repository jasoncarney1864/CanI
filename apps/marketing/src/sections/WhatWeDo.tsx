const CAPABILITIES = [
  {
    key: "legal",
    title: "Legal",
    question: "Can I paint my fence?",
    description:
      "Leases, contracts, HOA covenants, and filings. A plain-English answer with the exact clause spotlighted \u2014 not thirty pages of legalese.",
  },
  {
    key: "health",
    title: "Health",
    question: "Can I see a specialist without a referral?",
    description:
      "Health records and benefits documents. Understand what your plan actually covers and what your records actually say, with the source passage alongside every answer.",
  },
  {
    key: "finance",
    title: "Finance",
    question: "Can I pay this loan off early?",
    description:
      "Tax notices, loan agreements, and statements. Get a clear read on the terms you agreed to and the deadlines that matter, cited line by line.",
  },
] as const;

export function WhatWeDo() {
  return (
    <section id="what-we-do" className="section">
      <div className="section-inner">
        <p className="eyebrow">What it covers</p>
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
              <p className="capability-question">
                <span className="spotlight">&ldquo;{capability.question}&rdquo;</span>
              </p>
              <p>{capability.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
