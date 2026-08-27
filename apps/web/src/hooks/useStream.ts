import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useUi } from "../store";
import { getToken } from "../lib/api";

/** SSE subscription (ADR-006). Additive event names only (Rules §6.4).
 *  EventSource cannot send headers, so the JWT rides as ?token= (accepted by
 *  security.bearer_payload). Without a token the socket would 401 forever and
 *  the nav pill would stay "connecting". */
export function useStream(): void {
  const qc = useQueryClient();
  const { setSse, touch, setBanner, setMode, pushEvent } = useUi();

  useEffect(() => {
    if (!getToken()) return;
    const _base = ((import.meta.env.VITE_REFLEX_API as string | undefined) || (import.meta.env.VITE_API_URL as string | undefined) || "").replace(/\/$/, "");
    const url = `${_base ? _base : ""}/api/stream?token=${encodeURIComponent(getToken() ?? "")}`;
    const es = new EventSource(url);
    es.onopen = () => setSse(true);
    es.onerror = () => setSse(false);
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
    return () => es.close();
  }, [qc, setSse, touch, setBanner, setMode, pushEvent]);
}
