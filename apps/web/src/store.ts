import { create } from "zustand";

/** UI state only — server state lives in TanStack Query (TechSpec §5). */
interface UiEvent {
  at: string;
  type: string;
  detail?: string;
}

interface UiState {
  mode: string;
  banner: { kind: "DEGRADED" | "HALTED" | null; reason?: string };
  sseConnected: boolean;
  lastEventAt: string | null;
  events: UiEvent[];
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
  pushEvent: (e: UiEvent) => void;
  openEpisodeDrawer: (id: string | null) => void;
  openEvDrawer: (v: UiState["evAction"]) => void;
  openLedgerDrawer: (id: string | null) => void;
}

export const useUi = create<UiState>((set) => ({
  mode: "advisory",
  banner: { kind: null },
  sseConnected: false,
  lastEventAt: null,
  events: [],
  openEpisode: null,
  evAction: null,
  ledgerEpisode: null,
  setMode: (mode) => set({ mode }),
  setBanner: (banner) => set({ banner }),
  setSse: (sseConnected) => set({ sseConnected }),
  touch: () => set({ lastEventAt: new Date().toISOString() }),
  pushEvent: (e) => set((s) => ({ events: [e, ...s.events].slice(0, 12), lastEventAt: e.at })),
  openEpisodeDrawer: (openEpisode) => set({ openEpisode }),
  openEvDrawer: (evAction) => set({ evAction }),
  openLedgerDrawer: (ledgerEpisode) => set({ ledgerEpisode }),
}));
