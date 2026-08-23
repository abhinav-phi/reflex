import { create } from "zustand";

/** UI state only — server state lives in TanStack Query (TechSpec §5). */
interface UiState {
  mode: string;
  banner: { kind: "DEGRADED" | "HALTED" | null; reason?: string };
  sseConnected: boolean;
  lastEventAt: string | null;
  openEpisode: string | null; // episode drawer
  evAction: {
    actionId: string;
    formula: string;
    terms: { p: number; gain: number; cost: number; annoyance: number; ev: number };
    guard: Record<string, unknown>;
    policy: string;
  } | null;
  ledgerEpisode: string | null;
  setMode: (m: string) => void;
  setBanner: (b: UiState["banner"]) => void;
  setSse: (ok: boolean) => void;
  touch: () => void;
  openEpisodeDrawer: (id: string | null) => void;
  openEvDrawer: (v: UiState["evAction"]) => void;
  openLedgerDrawer: (id: string | null) => void;
}

export const useUi = create<UiState>((set) => ({
  mode: "advisory",
  banner: { kind: null },
  sseConnected: false,
  lastEventAt: null,
  openEpisode: null,
  evAction: null,
  ledgerEpisode: null,
  setMode: (mode) => set({ mode }),
  setBanner: (banner) => set({ banner }),
  setSse: (sseConnected) => set({ sseConnected }),
  touch: () => set({ lastEventAt: new Date().toISOString() }),
  openEpisodeDrawer: (openEpisode) => set({ openEpisode }),
  openEvDrawer: (evAction) => set({ evAction }),
  openLedgerDrawer: (ledgerEpisode) => set({ ledgerEpisode }),
}));
