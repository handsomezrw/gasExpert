import { create } from "zustand";

export interface MapOverlay {
  id: string;
  layerType: "evacuation_zone" | "valve_isolation" | "repair_plan";
  title: string;
  status: "pending" | "synced" | "failed";
  timestamp: number;
  error?: string;
}

interface OverlayState {
  overlays: MapOverlay[];
  pushOverlay: (overlay: Omit<MapOverlay, "id" | "timestamp">) => void;
  updateOverlayStatus: (id: string, status: MapOverlay["status"], error?: string) => void;
  clearOverlays: () => void;
  /** Count of non-synced overlays */
  pendingCount: number;
}

let overlayCounter = 0;

export const useOverlayStore = create<OverlayState>((set) => ({
  overlays: [],

  pendingCount: 0,

  pushOverlay: (overlay) =>
    set((state) => {
      const id = `overlay-${++overlayCounter}`;
      const entry: MapOverlay = {
        ...overlay,
        id,
        timestamp: Date.now(),
      };
      return {
        overlays: [...state.overlays, entry],
        pendingCount: state.overlays.filter((o) => o.status !== "synced").length + 1,
      };
    }),

  updateOverlayStatus: (id, status, error) =>
    set((state) => ({
      overlays: state.overlays.map((o) =>
        o.id === id ? { ...o, status, error } : o,
      ),
      pendingCount: state.overlays.filter((o) =>
        o.id === id ? status !== "synced" : o.status !== "synced",
      ).length,
    })),

  clearOverlays: () => set({ overlays: [], pendingCount: 0 }),
}));
