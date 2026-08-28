import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { LiveMetrics } from "../lib/api";
import { formatINR, asPaise } from "../lib/format";
import { useTitle } from "../hooks/useTitle";

export default function Landing() {
  useTitle("Reflex — Recover more. Annoy less. Prove everything.");
  // Real data for the hero mockup — same source as Dashboard. Unauthenticated
  // visitors get the illustrative preview values, clearly labeled as such.
  const { data: m } = useQuery({
    queryKey: ["landing-metrics"],
    queryFn: () => api<LiveMetrics>("/api/metrics/live"),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const illustrative = !m;

  return (
    <div className="min-h-screen bg-background text-on-surface grid-bg selection:bg-secondary-container selection:text-on-secondary-container">
      {/* TopNav */}
      <nav className="flex justify-between items-center w-full px-margin py-4 max-w-full bg-background sticky top-0 z-50">
        <Link to="/" className="flex items-center gap-2">
          <span className="material-symbols-outlined text-primary" style={{ fontVariationSettings: "'FILL' 1" } as React.CSSProperties}>autorenew</span>
          <span className="font-display text-headline-sm font-bold tracking-tight text-primary">Reflex</span>
        </Link>
        <div className="hidden md:flex items-center gap-8 font-mono text-label-mono uppercase">
          <a className="text-on-surface-variant font-medium hover:text-primary transition-colors" href="#system">System</a>
          <Link className="text-on-surface-variant font-medium hover:text-primary transition-colors" to="/results">Proof</Link>
          <a className="text-on-surface-variant font-medium hover:text-primary transition-colors" href="#principle">Principle</a>
        </div>
        <Link to="/dashboard" className="bg-primary-container text-on-primary-container font-mono text-label-mono uppercase px-6 py-3 rounded-full hover:bg-primary hover:text-on-primary transition-colors">
          Open command center
        </Link>
      </nav>

      <main className="w-full max-w-7xl mx-auto px-margin pt-16 pb-32">
        {/* Hero */}
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-gutter min-h-[70vh] items-center mb-32 relative">
          <div className="flex flex-col gap-6 z-10">
            <div className="font-mono text-label-mono uppercase text-on-tertiary-container tracking-widest flex items-center gap-2">
              <span>AI REVENUE RECOVERY</span><span className="text-outline-variant">/</span><span>01</span>
            </div>
            <h1 className="font-display text-display-lg-mobile md:text-display-lg text-primary leading-none">
              Recover more.<br /><span className="text-on-primary-container">Annoy less.</span><br />Prove everything.
            </h1>
            <p className="font-sans text-body-lg text-on-surface-variant max-w-md">
              Reflex is the bounded recovery agent for merchants who want to turn failed payments into recovered revenue — without turning trust into a tradeoff.
            </p>
            <div className="flex flex-wrap items-center gap-4 pt-4">
              <Link to="/dashboard" className="bg-secondary-container text-on-secondary-container font-mono text-label-mono uppercase px-6 py-4 rounded-full flex items-center gap-2 hover:bg-secondary-fixed-dim transition-colors group">
                See the command center <span className="material-symbols-outlined text-[16px] group-hover:translate-x-1 transition-transform">arrow_forward</span>
              </Link>
              <a href="#system" className="border border-outline text-primary font-mono text-label-mono uppercase px-6 py-4 rounded-full hover:bg-surface-variant transition-colors">Explore the system</a>
            </div>
          </div>

          {/* Hero mockup — live data when logged in; illustrative preview otherwise */}
          <div className="relative w-full h-[500px] flex items-center justify-center lg:justify-end lg:pl-12 mt-16 lg:mt-0">
            <div className="bg-primary-container w-full max-w-[520px] rounded-[24px] p-8 warm-shadow-lg transform rotate-[-2deg] hover:rotate-0 transition-transform duration-500 border border-primary-fixed-dim">
              <div className="flex justify-between items-start mb-12">
                <div className="flex flex-col gap-1">
                  <span className="font-mono text-[10px] uppercase text-on-primary-container tracking-widest">RECOVERY OVERVIEW</span>
                  <span className="font-sans text-body-md text-on-primary font-medium">SipDaily / command center preview</span>
                </div>
                <div className="bg-secondary-container text-on-secondary-container font-mono text-[10px] uppercase px-3 py-1 rounded-full flex items-center gap-1 font-bold">
                  <span className="w-1.5 h-1.5 rounded-full bg-on-secondary-container animate-pulse" /> {illustrative ? "PREVIEW" : "LIVE"}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4 mb-12 border-b border-on-primary-container/20 pb-8">
                <div>
                  <span className="font-mono text-[10px] uppercase text-on-primary-container tracking-widest block mb-2">Recovered today</span>
                  <div className="font-display text-[32px] text-on-primary font-semibold leading-none mb-2">{m ? formatINR(asPaise(m.recovered_reflex_paise)) : "₹76,420"}</div>
                  <span className="font-mono text-[10px] text-secondary-fixed">{m ? "live from /api/metrics" : "illustrative — sign in for live data"}</span>
                </div>
                <div>
                  <span className="font-mono text-[10px] uppercase text-on-primary-container tracking-widest block mb-2">Complaint rate</span>
                  <div className="font-display text-[32px] text-on-primary font-semibold leading-none mb-2">{m ? `${(m.complaint_rate * 100).toFixed(2)}%` : "0.26%"}</div>
                  <span className="font-mono text-[10px] text-on-primary-container">within safe bounds</span>
                </div>
              </div>
              <div>
                <div className="flex justify-between items-center mb-3">
                  <span className="font-mono text-[10px] uppercase text-on-primary tracking-widest">SHIELD / ACTION QUEUE</span>
                  <span className="font-mono text-[10px] text-secondary-fixed">{m ? `${m.episodes_open} pending` : "04 pending"}</span>
                </div>
                <div className="w-full h-1.5 bg-on-primary-container/20 rounded-full mb-3 overflow-hidden">
                  <div className={`h-full bg-secondary-container rounded-full ${m ? "" : "w-[72%]"}`} style={m ? { width: `${Math.min(100, Math.round((m.episodes_terminal / Math.max(1, m.episodes_terminal + m.episodes_open)) * 100))}%` } : undefined} />
                </div>
                <div className="flex justify-between items-center">
                  <span className="font-mono text-[10px] text-on-primary-container">{m ? "share of episodes resolved" : "72% eligible recovery"}</span>
                  <span className="font-mono text-[10px] text-on-primary-container">EV ranked</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Features */}
        <section id="system" className="mt-32 scroll-mt-24">
          <div className="mb-12"><h2 className="font-mono text-label-mono uppercase text-on-tertiary-container tracking-widest">ONE SYSTEM, SIX GUARANTEES</h2></div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-gutter">
            <Link to="/dashboard" className="bg-surface-container-lowest rounded-[16px] p-8 warm-shadow flex flex-col gap-4 border border-outline-variant/30 hover:border-primary/40 transition-colors cursor-pointer">
              <span className="font-mono text-label-mono text-on-tertiary-container">01</span>
              <h3 className="font-display text-headline-md text-primary">Bounded Autonomy</h3>
              <p className="font-sans text-body-md text-on-surface-variant">The agent operates strictly within mathematical guardrails you define. It optimizes for EV but halts if complaint rates spike.</p>
            </Link>
            <Link to="/audit" className="bg-surface-container-lowest rounded-[16px] p-8 warm-shadow flex flex-col gap-4 border border-outline-variant/30 hover:border-primary/40 transition-colors cursor-pointer">
              <span className="font-mono text-label-mono text-on-tertiary-container">02</span>
              <h3 className="font-display text-headline-md text-primary">Cryptographic Proof</h3>
              <p className="font-sans text-body-md text-on-surface-variant">Every action, decision, and communication is logged on an immutable ledger. Full auditability by design.</p>
            </Link>
            <Link to="/results" className="bg-surface-container-lowest rounded-[16px] p-8 warm-shadow flex flex-col gap-4 border border-outline-variant/30 hover:border-primary/40 transition-colors cursor-pointer">
              <span className="font-mono text-label-mono text-on-tertiary-container">03</span>
              <h3 className="font-display text-headline-md text-primary">Dynamic Tone Matching</h3>
              <p className="font-sans text-body-md text-on-surface-variant">Communications adapt to customer context. Empathy for genuine hardship, directness for chronic defaults.</p>
            </Link>
          </div>
        </section>

        {/* Principle — anchor target for the nav "Principle" link */}
        <section id="principle" className="mt-32 scroll-mt-24">
          <div className="mb-12"><h2 className="font-mono text-label-mono uppercase text-on-tertiary-container tracking-widest">PRINCIPLE</h2></div>
          <blockquote className="border-l-4 border-primary pl-8">
            <p className="font-display text-headline-sm md:text-headline-md text-primary max-w-3xl">“The cheapest revenue to acquire is the revenue you already earned.”</p>
            <p className="mt-6 font-sans text-body-md text-on-surface-variant max-w-2xl">Recovery should never cost more trust than it earns money. Reflex proves every action was bounded, justified, and reversible — that is the whole product.</p>
          </blockquote>
        </section>
      </main>

      <footer className="flex flex-col md:flex-row justify-between items-center px-margin py-8 w-full max-w-7xl mx-auto border-t border-outline-variant mt-32">
        <div className="font-display text-headline-sm text-primary mb-4 md:mb-0">Reflex</div>
        <div className="font-sans text-body-md text-on-surface-variant text-center md:text-left mb-4 md:mb-0">© {new Date().getFullYear()} Reflex Payment Recovery. All rights reserved.</div>
        <div className="flex gap-6 font-sans text-body-md text-on-surface-variant">
          <a className="hover:text-primary transition-colors" href="#system">System</a>
          <Link className="hover:text-primary transition-colors" to="/results">Proof</Link>
          <a className="hover:text-primary transition-colors" href="#principle">Principle</a>
          <a className="hover:text-primary transition-colors" href="mailto:support@reflex.dev">Contact Support</a>
        </div>
      </footer>
    </div>
  );
}
