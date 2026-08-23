import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, setToken } from "../lib/api";
import { SimulatedBadge, TestModeBadge } from "../components/Chips";

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
    <div className="flex min-h-screen items-center justify-center bg-cmd-bg p-24">
      <form
        onSubmit={submit}
        className="w-full max-w-400 rounded-card border border-cmd-border bg-cmd-surface p-32"
      >
        <h1 className="text-2xl font-bold text-ink-dark">
          Refl<span className="text-ai-accent">e</span>x
        </h1>
        <p className="mt-4 flex items-center gap-8 text-xs text-ink-muted">
          bounded recovery agent <SimulatedBadge /> <TestModeBadge />
        </p>

        <label className="mt-24 block text-[11px] uppercase tracking-wide text-ink-muted">Email</label>
        <input
          className="mt-4 w-full rounded-btn border border-cmd-border bg-black/30 px-12 py-8 text-sm outline-none focus:border-primary"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <label className="mt-16 block text-[11px] uppercase tracking-wide text-ink-muted">Password</label>
        <input
          type="password"
          className="mt-4 w-full rounded-btn border border-cmd-border bg-black/30 px-12 py-8 text-sm outline-none focus:border-primary"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {err && <p className="mt-12 text-xs text-red-400" role="alert">{err}</p>}
        <button
          disabled={busy}
          className="mt-24 w-full rounded-btn bg-primary py-10 text-sm font-semibold hover:bg-primary-hover disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="mt-16 font-mono text-[11px] leading-relaxed text-slate-500">
          seeded demo users: admin@ / approver@ / operator@ / viewer@reflex.dev · password reflex-demo
        </p>
      </form>
    </div>
  );
}
