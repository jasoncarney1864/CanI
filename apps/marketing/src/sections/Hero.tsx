import { useEffect, useRef, useState } from "react";

const SWEEP_MS = 1800;

// The answer card is the page's one demonstration: a question, a plain-English answer, and
// the source clause with the deciding sentence spotlighted. It is a static illustration of
// the product's output, labelled as such, not a live query.
//
// The highlight is visible by default and the sweep is an enhancement on top: it plays once
// when the card scrolls into view (on a phone the card starts below the fold), and the
// class is removed by a timer afterwards. A browser that never ticks the animation, as the
// preview pane did on 2026-11-13, therefore still ends on the highlighted sentence rather
// than on an unmarked clause.
function AnswerCard() {
  const ref = useRef<HTMLElement>(null);
  const [sweeping, setSweeping] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || !("IntersectionObserver" in window)) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let timer: number | undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        observer.disconnect();
        setSweeping(true);
        timer = window.setTimeout(() => setSweeping(false), SWEEP_MS);
      },
      { threshold: 0.6 },
    );
    observer.observe(node);
    return () => {
      observer.disconnect();
      window.clearTimeout(timer);
    };
  }, []);

  return (
    <figure
      ref={ref}
      className="answer-card"
      aria-label="Illustrative example of a CanI answer"
    >
      <p className="answer-card-question">
        <span className="answer-card-label">You asked</span>
        Can I sublet my apartment?
      </p>
      <div className="answer-card-answer">
        <span className="answer-card-verdict">Yes, with written consent</span>
        <p>
          Your lease allows subletting if the landlord agrees in writing first, and says
          that consent cannot be unreasonably withheld.
        </p>
      </div>
      <blockquote className="answer-card-source">
        <p>
          12. Assignment and Subletting. Tenant shall not assign this Lease.{" "}
          <mark className={sweeping ? "spotlight spotlight--sweep" : "spotlight"}>
            Tenant may sublet the Premises only with the prior written consent of
            Landlord, which shall not be unreasonably withheld.
          </mark>{" "}
          Any sublease made without such consent is void.
        </p>
        <footer>Lease Agreement &middot; Section 12 &middot; page 7</footer>
      </blockquote>
      <figcaption>Illustrative example</figcaption>
    </figure>
  );
}

export function Hero() {
  return (
    <section className="hero">
      <div className="section-inner hero-inner">
        <div className="hero-copy">
          <p className="eyebrow">Your documents, illuminated</p>
          <h1>
            &ldquo;Can I&hellip;?&rdquo; Ask your documents. Get a{" "}
            <span className="spotlight">straight answer.</span>
          </h1>
          <p className="hero-subhead">
            CanI answers from the paperwork that actually governs your life, and cites
            every answer back to the exact passage it came from.
          </p>
          <div className="hero-actions">
            <a className="button button--primary" href="https://app.canido.co/auth/login">
              Get started free
            </a>
            <a className="button button--secondary" href="#what-we-do">
              See what it covers
            </a>
          </div>
        </div>
        <AnswerCard />
      </div>
    </section>
  );
}
