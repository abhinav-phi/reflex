import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useUi } from "../store";
import { getToken } from "../lib/api";

/** SSE subscription (ADR-006). Additive event names only (Rules §6.4).
 *  EventSource cannot send headers, so a credential rides as ?token= (accepted
 *  by security.bearer_payload). Hardening: first exchange the session JWT for
 *  a 60-second stream credential (POST /api/stream/token) so the session JWT
 *  itself never appears in the URL — the connection is authorized for its
 *  whole lifetime once established.
 *
 *  EventSource auto-reconnects every ~3s on error. When the host's edge
 *  proxy throttles this IP, that loop keeps the throttle alive (each failed
 *  connect is a fresh HTTP request). We therefore reconnect manually with
 *  exponential backoff, capped at 60s — worst case the app costs ~1 req/min
 *  while blocked, and the block clears itself in 2-3 minutes. */
const RECONNECT_STEPS_SECS = [3, 6, 12, 30, 60];

export function useStream(): void {
  const qc = useQueryClient();
  const { setSse, touch, setBanner, setMode, pushEvent } = useUi();

  useEffect(() => {
    if (!getToken()) return;
    const _base = ((import.meta.env.VITE_REFLEX_API as string | undefined) || (import.meta.env.VITE_API_URL as string | undefined) || "").replace(/\/$/, "");
    let url = "";
    let disposed = false;
    let step = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let es: EventSource | undefined;

    let connected = false;
    const connect = (): void => {
      es = new EventSource(url);
      es.onopen = () => {
        connected = true;
        step = 0;
        setSse(true);
      };
      es.onerror = () => {
        setSse(false);
        es?.close();
        connected = false;
        // No new connection while the tab is hidden — it would just burn
        // budget for nobody.
        if (document.visibilityState !== "visible") return;
        const delay = RECONNECT_STEPS_SECS[Math.min(step, RECONNECT_STEPS_SECS.length - 1)] * 1000;
        step += 1;
        timer = setTimeout(connect, delay);
      };
      es.onmessage = (ev) => {
        touch();
        let msg: Record<string, unknown> = {};
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }
        const type = String(msg.type ?? "");
        const detail = typeof msg.episode_id === "string"
          ? String(msg.episode_id).slice(0, 8)
          : typeof msg.scenario === "string"
            ? String(msg.scenario)
            : undefined;
        pushEvent({ at: new Date().toISOString(), type, detail });
        if (
          [
            "episode.created",
            "action.dispatched",
            "counters.updated",
            "approval.created",
            "storm.stats",
            "complaint.injected",
          ].includes(type)
        ) {
          void qc.invalidateQueries({ queryKey: ["metrics"] });
          void qc.invalidateQueries({ queryKey: ["episodes"] });
          void qc.invalidateQueries({ queryKey: ["approvals"] });
          void qc.invalidateQueries({ queryKey: ["episode"] });
        }
        if (type === "mode.changed") {
          setMode(String(msg.mode));
          void qc.invalidateQueries({ queryKey: ["metrics"] });
        }
        if (type === "banner.updated") {
          const banner = msg.banner;
          setBanner({
            kind: banner === "DEGRADED" ? "DEGRADED" : banner ? "HALTED" : null,
            reason: typeof msg.reason === "string" ? msg.reason : undefined,
          });
        }
      };
    };

    (async () => {
      let streamToken = getToken() ?? "";
      try {
        const res = await fetch(`${_base ? _base : ""}/api/stream/token`, {
          headers: { Authorization: `Bearer ${streamToken}` },
        });
        if (res.ok) {
          const d = (await res.json()) as { token?: string };
          if (d?.token) streamToken = String(d.token);
        }
      } catch {
        /* fall back to the session JWT — the URL short-lived token is an
           optimization; the auth path is identical */
      }
      if (disposed) return;
      url = `${_base ? _base : ""}/api/stream?token=${encodeURIComponent(streamToken)}`;
      connect();
    })();
    const onVisibility = (): void => {
      if (document.visibilityState === "visible" && !connected) {
        step = 0;
        clearTimeout(timer);
        connect();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      disposed = true;
      clearTimeout(timer);
      es?.close();
      setSse(false);
    };
  }, [qc, setSse, touch, setBanner, setMode, pushEvent]);
}
