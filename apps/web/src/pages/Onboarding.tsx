import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, post } from "../lib/api";
import { ControlBar } from "../components/ControlBar";
import { TestModeBadge } from "../components/Chips";

/** Onboarding (AppFlow §2): keys check → webhook → guardrails → mode. */
export default function Onboarding() {
  const nav = useNavigate();
  const [step, setStep] = useState(0);
  const [keyId, setKeyId] = useState("");
  const [keySecret, setKeySecret] = useState("");
  const [checkMsg, setCheckMsg] = useState<string | null>(null);
  const [mode, setModeChoice] = useState("advisory");
  const [caps, setCaps] = useState(4);
  const [contacts, setContacts] = useState(2);

  useEffect(() => {
    api<{ configured: boolean }>("/api/onboarding/state")
      .then((s) => {
        if (s.configured) setStep(1);
      })
      .catch(() => undefined);
  }, []);

  async function verifyKeys() {
    try {
      await post("/api/onboarding/verify_keys", { key_id: keyId, key_secret: keySecret });
      setCheckMsg("✓ [TEST MODE] ₹1 test order created and cancelled");
      setStep(1);
    } catch (ex) {
      setCheckMsg(`✗ ${ex instanceof Error ? ex.message : "check failed"}`);
    }
  }

  async function saveGuardrails() {
    await post("/api/onboarding/guardrails", {
      caps_per_episode: caps,
      contacts_per_day: contacts,
      quiet_hours: "21:00-09:00",
      budget_paise_daily: 500000,
      approval_threshold_paise: 5000000,
    });
    setStep(3);
  }

  return (
    <div className="min-h-screen bg-cmd-bg text-ink-dark">
      <ControlBar />
      <main className="mx-auto max-w-[720px] px-24 pb-48">
        <h1 className="mt-32 text-xl font-semibold">Onboarding — SipDaily (demo merchant)</h1>
        <ol className="mt-16 space-y-16">
          <li className={`rounded-card border p-16 ${step === 0 ? "border-primary" : "border-cmd-border"}`}>
            <h2 className="text-sm font-semibold">1 · Razorpay test-mode keys <TestModeBadge /></h2>
            <input placeholder="rzp_test_…" value={keyId} onChange={(e) => setKeyId(e.target.value)}
              className="mt-8 w-full rounded-btn border border-cmd-border bg-black/30 px-12 py-8 font-mono text-xs outline-none focus:border-primary" />
            <input placeholder="key secret" type="password" value={keySecret} onChange={(e) => setKeySecret(e.target.value)}
              className="mt-8 w-full rounded-btn border border-cmd-border bg-black/30 px-12 py-8 font-mono text-xs outline-none focus:border-primary" />
            <button onClick={() => void verifyKeys()} className="mt-8 rounded-btn bg-primary px-16 py-8 text-xs font-semibold">
              Verify connectivity (₹1 order + cancel)
            </button>
            {checkMsg && <p className="mt-8 text-xs text-slate-300">{checkMsg}</p>}
          </li>

          <li className={`rounded-card border p-16 ${step === 1 ? "border-primary" : "border-cmd-border opacity-70"}`}>
            <h2 className="text-sm font-semibold">2 · Webhook endpoint & HMAC secret</h2>
            <p className="mt-8 font-mono text-xs text-slate-400">POST /webhooks/razorpay — verified via X-Razorpay-Signature; duplicates → 200 dedup</p>
            {step === 1 && (
              <button onClick={() => setStep(2)} className="mt-8 rounded-btn border border-cmd-border px-16 py-6 text-xs">
                Next →
              </button>
            )}
          </li>

          <li className={`rounded-card border p-16 ${step === 2 ? "border-primary" : "border-cmd-border opacity-70"}`}>
            <h2 className="text-sm font-semibold">3 · Guardrail defaults (editable; hard bounds enforced)</h2>
            <label className="mt-8 block text-xs text-slate-400">caps / episode: {caps}</label>
            <input type="range" min={1} max={4} value={caps} onChange={(e) => setCaps(Number(e.target.value))} />
            <label className="mt-8 block text-xs text-slate-400">contacts / customer / day: {contacts}</label>
            <input type="range" min={1} max={2} value={contacts} onChange={(e) => setContacts(Number(e.target.value))} />
            <p className="mt-8 text-[11px] text-slate-500">
              quiet hours 21:00–09:00 IST · daily budget ₹5,000 · approval &gt; ₹50,000
            </p>
            {step === 2 && (
              <button onClick={() => void saveGuardrails()} className="mt-8 rounded-btn bg-primary px-16 py-6 text-xs font-semibold">
                Save (ledgered)
              </button>
            )}
          </li>

          <li className={`rounded-card border p-16 ${step === 3 ? "border-primary" : "border-cmd-border opacity-70"}`}>
            <h2 className="text-sm font-semibold">4 · Choose starting mode</h2>
            <select value={mode} onChange={(e) => setModeChoice(e.target.value)} className="mt-8 rounded-btn border border-cmd-border bg-black/30 px-12 py-8 text-sm">
              <option value="advisory">Advisory (recommended)</option>
              <option value="autonomous">Autonomous (bounded)</option>
            </select>
            {step === 3 && (
              <button
                onClick={() =>
                  void post("/api/onboarding/mode", { mode }).then(() => nav("/dashboard"))
                }
                className="ml-12 rounded-btn bg-primary px-16 py-6 text-xs font-semibold"
              >
                Finish → dashboard
              </button>
            )}
          </li>
        </ol>
      </main>
    </div>
  );
}
