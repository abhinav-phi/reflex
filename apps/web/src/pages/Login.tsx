import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, setToken } from "../lib/api";

export default function Login() {
  const nav = useNavigate();
  const [email, setEmail] = useState("admin@reflex.dev");
  const [password, setPassword] = useState("reflex-demo");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api<{ token: string; role: string }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(r.token);
      void api<{ configured: boolean }>("/api/onboarding/state")
        .then((s) => nav(s.configured ? "/dashboard" : "/onboarding"))
        .catch(() => nav("/dashboard"));
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-surface bg-grid-paper flex items-center justify-center p-4">
      <main className="w-full max-w-5xl bg-surface-container-lowest rounded-2xl shadow-warm-ambient flex flex-col md:flex-row overflow-hidden border border-outline-variant">
        {/* Left — Forest */}
        <div className="bg-primary-container p-8 md:p-12 md:w-1/2 flex flex-col justify-between text-on-primary">
          <div>
            <div className="flex items-center gap-2 mb-16">
              <span className="material-symbols-outlined text-secondary-container" style={{ fontVariationSettings: "'FILL' 1" } as React.CSSProperties}>polyline</span>
              <span className="font-display text-headline-sm font-bold text-on-primary">Reflex</span>
            </div>
            <div className="mb-4"><span className="font-mono text-label-mono text-secondary-container uppercase tracking-widest">COMMAND CENTER</span></div>
            <h1 className="font-display text-display-lg-mobile md:text-display-lg text-on-primary mb-6 leading-none">Clarity for<br />every failed<br />payment.</h1>
            <p className="font-sans text-body-md text-primary-fixed-dim max-w-sm">See what happened, what Reflex recommends, and exactly why the Shield allowed it.</p>
          </div>
          <div className="mt-16 md:mt-0">
            <div className="w-full h-px bg-on-primary/20 mb-6" />
            <p className="font-display text-lg italic text-primary-fixed-dim font-light">“The cheapest revenue to acquire is the revenue you already earned.”</p>
          </div>
        </div>

        {/* Right — White */}
        <div className="p-8 md:p-12 md:w-1/2 flex flex-col justify-center">
          <div className="mb-8">
            <p className="font-sans text-body-md text-on-surface-variant mb-2">Welcome back, operator.</p>
            <h2 className="font-display text-headline-md text-on-surface mb-3">Enter the command center.</h2>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-label-mono text-on-surface-variant">bounded recovery agent</span>
              <span className="font-mono text-[10px] uppercase tracking-widest border border-tertiary-container text-tertiary-container px-2 py-1 rounded">[SIMULATED]</span>
              <span className="font-mono text-[10px] uppercase tracking-widest border border-outline text-outline px-2 py-1 rounded">TEST MODE</span>
            </div>
          </div>

          <form onSubmit={submit} className="space-y-6" aria-label="Login form">
            <div>
              <label className="block font-mono text-label-mono text-on-surface-variant mb-2 uppercase" htmlFor="email">Email</label>
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                className="w-full bg-surface-container border-0 rounded-lg px-4 py-3 font-sans text-body-md text-on-surface focus:ring-2 focus:ring-primary focus:bg-surface-container-lowest transition-colors"
                placeholder="operator@reflex.dev"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="block font-mono text-label-mono text-on-surface-variant mb-2 uppercase" htmlFor="password">Password</label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                className="w-full bg-surface-container border-0 rounded-lg px-4 py-3 font-sans text-body-md text-on-surface focus:ring-2 focus:ring-primary focus:bg-surface-container-lowest transition-colors"
                placeholder="••••••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {err && <p className="text-xs text-error" role="alert">{err}</p>}
            <button disabled={busy} type="submit" className="w-full bg-primary-container text-on-primary hover:bg-primary transition-colors font-sans text-body-md py-3 rounded-full flex items-center justify-center font-medium disabled:opacity-50">
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <div className="mt-8 border-t border-outline-variant pt-6">
            <p className="font-mono text-[10px] text-outline uppercase tracking-wider leading-relaxed">seeded demo users: admin@ / approver@ / operator@ / viewer@reflex.dev · password reflex-demo</p>
          </div>
        </div>
      </main>
    </div>
  );
}
