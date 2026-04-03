import { create } from "zustand";
import type { PanelData, ToolCallEvent } from "@/types";

interface PanelState {
  toolCalls: ToolCallEvent[];
  panelData: PanelData[];

  addToolCall: (tc: ToolCallEvent) => void;
  updateToolCall: (id: string, update: Partial<ToolCallEvent>) => void;
  addPanelData: (data: PanelData) => void;
  clearPanel: () => void;
}

export const usePanelStore = create<PanelState>((set) => ({
  toolCalls: [],
  panelData: [],

  addToolCall: (tc) =>
    set((state) => ({ toolCalls: [...state.toolCalls, tc] })),

  updateToolCall: (id, update) =>
    set((state) => ({
      toolCalls: state.toolCalls.map((tc) =>
        tc.id === id ? { ...tc, ...update } : tc,
      ),
    })),

  addPanelData: (data) =>
    set((state) => ({ panelData: [...state.panelData, data] })),

  clearPanel: () => set({ toolCalls: [], panelData: [] }),
}));
