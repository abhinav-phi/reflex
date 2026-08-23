import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useUi } from "../store";
import { getToken } from "../lib/api";

/** SSE subscription (ADR-006). Additive event names only (Rules §6.4). */
export function useStream(): void {
  const qc = useQueryClient();
  const { setSse, touch, setBanner, setMode } = useUi();

  useEffect(() => {
    if (!getToken()) return;
    const es = new EventSource("/api/stream");
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
      if (
        [
          "episode.created",
          "action.dispatched",
          "counters.updated",
          "approval.created",
          "storm.stats",
        ].includes(type)
      ) {
        void qc.invalidateQueries({ queryKey: ["metrics"] });
        void qc.invalidateQueries({ queryKey: ["episodes"] });
        void qc.invalidateQueries({ queryKey: ["approvals"] });
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
  }, [qc, setSse, touch, setBanner, setMode]);
}
