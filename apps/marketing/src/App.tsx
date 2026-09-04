import { Hero } from "./sections/Hero.tsx";
import { WhatWeDo } from "./sections/WhatWeDo.tsx";
import { AiPositioning } from "./sections/AiPositioning.tsx";
import { DemoRequestSection } from "./sections/DemoRequestSection.tsx";

function LandingPage() {
  return (
    <main>
      <Hero />
      <WhatWeDo />
      <AiPositioning />
      <DemoRequestSection />
    </main>
  );
}

export function App() {
  return (
    <>
      <header className="site-header">
        <div className="section-inner site-header-inner">
          <a className="site-logo" href="/">
            CanI<span className="site-logo-dot">.</span>
          </a>
          <a className="button button--primary button--small" href="https://app.canido.co/auth/login">
            Get started
          </a>
        </div>
      </header>

      <LandingPage />

      <footer className="site-footer">
        <div className="section-inner">
          <p>
            &copy; {new Date().getFullYear()} CanI. Answers grounded in your documents — not
            legal, medical, or financial advice.
          </p>
        </div>
      </footer>
    </>
  );
}
