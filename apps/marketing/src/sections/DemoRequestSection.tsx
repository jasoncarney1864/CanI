import { DemoRequestForm } from "../DemoRequestForm.tsx";

export function DemoRequestSection() {
  return (
    <section id="demo-request" className="section">
      <div className="section-inner demo-request-inner">
        <div className="demo-request-copy">
          <h2>See Sondra Keys on your own research</h2>
          <p>
            Tell us a bit about what you're working on, and we'll follow up
            to set up a walkthrough.
          </p>
        </div>
        <div className="demo-request-form-wrapper">
          <DemoRequestForm />
        </div>
      </div>
    </section>
  );
}
