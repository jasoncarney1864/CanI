import { Hero } from "./sections/Hero.tsx";
import { WhatWeDo } from "./sections/WhatWeDo.tsx";
import { AiPositioning } from "./sections/AiPositioning.tsx";
import { DemoRequestSection } from "./sections/DemoRequestSection.tsx";
import { CreateAccountPage } from "./CreateAccountPage.tsx";

// Two static routes total — plain pathname branching rather than pulling
// in a router library, matching this repo's existing "no UI framework or
// router" stance for a small, mostly-static site.
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
  const isCreateAccountPage = window.location.pathname === "/create-account";

  return (
    <>
      <header className="site-header">
        <div className="section-inner site-header-inner">
          <a className="site-logo" href="/">
            Sondra Keys
          </a>
          {!isCreateAccountPage && (
            <a className="button button--primary button--small" href="#demo-request">
              Request a Demo
            </a>
          )}
        </div>
      </header>

      {isCreateAccountPage ? <CreateAccountPage /> : <LandingPage />}

      <footer className="site-footer">
        <div className="section-inner">
          <p>&copy; {new Date().getFullYear()} Sondra Keys. Nevada legal research, not legal advice.</p>
        </div>
      </footer>
    </>
  );
}
