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
    <div className="min-h-screen bg-background text-on-surface">
      <ControlBar />
      <main className="mx-auto max-w-[720px] px-4 md:px-24 pb-48">
        <h1 className="mt-8 md:mt-32 font-display text-headline-md text-primary">Onboarding — SipDaily (demo merchant)</h1>
        <ol className="mt-8 md:mt-16 space-y-6 md:space-y-8">
          <li className={`rounded-xl border p-6 md:p-6 warm-shadow ${step === 0 ? "border-primary bg-surface-container-lowest" : "border-outline-variant bg-surface-container-lowest opacity-70"}`}>
            <h2 className="font-display text-headline-sm text-primary">1 · Razorpay test-mode keys <TestModeBadge /></h2>
            <input placeholder="rzp_test_…" value={keyId} onChange={(e) => setKeyId(e.target.value)} className="mt-4 w-full rounded-lg border border-outline-variant bg-surface-container px-4 py-3 font-mono text-xs outline-none focus:ring-2 focus:ring-primary" />
            <input placeholder="key secret" type="password" value={keySecret} onChange={(e) => setKeySecret(e.target.value)} className="mt-4 w-full rounded-lg border border-outline-variant bg-surface-container px-4 py-3 font-mono text-xs outline-none focus:ring-2 focus:ring-primary" />
            <button onClick={() => void verifyKeys()} className="mt-4 rounded-full bg-primary-container text-on-primary px-6 py-3 text-xs font-mono font-semibold hover:bg-primary">Verify connectivity (₹1 order + cancel)</button>
            {checkMsg && <p className="mt-4 text-xs text-on-surface-variant">{checkMsg}</p>}
          </li>

          <li className={`rounded-xl border p-6 md:p-6 warm-shadow ${step === 1 ? "border-primary bg-surface-container-lowest" : "border-outline-variant bg-surface-container-lowest opacity-70"}`}>
            <h2 className="font-display text-headline-sm text-primary">2 · Webhook endpoint & HMAC secret</h2>
            <p className="mt-4 font-mono text-xs text-on-surface-variant">POST /webhooks/razorpay — verified via X-Razorpay-Signature; duplicates → 200 dedup</p>
            {step === 1 && <button onClick={() => setStep(2)} className="mt-4 rounded-full border border-outline-variant px-6 py-2 text-xs">Next →</button>}
          </li>

          <li className={`rounded-xl border p-6 md:p-6 warm-shadow ${step === 2 ? "border-primary bg-surface-container-lowest" : "border-outline-variant bg-surface-container-lowest opacity-70"}`}>
            <h2 className="font-display text-headline-sm text-primary">3 · Guardrail defaults (editable; hard bounds enforced)</h2>
            <label className="mt-4 block font-mono text-label-mono text-on-surface-variant">caps / episode: {caps}</label>
            <input type="range" min={1} max={4} value={caps} onChange={(e) => setCaps(Number(e.target.value))} className="w-full" />
            <label className="mt-4 block font-mono text-label-mono text-on-surface-variant">contacts / customer / day: {contacts}</label>
            <input type="range" min={1} max={2} value={contacts} onChange={(e) => setContacts(Number(e.target.value))} className="w-full" />
            <p className="mt-4 font-mono text-[11px] text-outline">quiet hours 21:00–09:00 IST · daily budget ₹5,000 · approval &gt; ₹50,000</p>
            {step === 2 && <button onClick={() => void saveGuardrails()} className="mt-4 rounded-full bg-primary-container text-on-primary px-6 py-2 text-xs font-mono font-semibold">Save (ledgered)</button>}
          </li>

          <li className={`rounded-xl border p-6 md:p-6 warm-shadow ${step === 3 ? "border-primary bg-surface-container-lowest" : "border-outline-variant bg-surface-container-lowest opacity-70"}`}>
            <h2 className="font-display text-headline-sm text-primary">4 · Choose starting mode</h2>
            <select value={mode} onChange={(e) => setModeChoice(e.target.value)} className="mt-4 rounded-lg border border-outline-variant bg-surface-container px-4 py-3 text-sm">
              <option value="advisory">Advisory (recommended)</option>
              <option value="autonomous">Autonomous (bounded)</option>
            </select>
            {step === 3 && <button onClick={() => void post("/api/onboarding/mode", { mode }).then(() => nav("/dashboard"))} className="ml-4 rounded-full bg-primary-container text-on-primary px-6 py-2 text-xs font-mono font-semibold">Finish → dashboard</button>}
          </li>
        </ol>
      </main>
    </div>
  );
}
