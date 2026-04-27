import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ChatMessage, ChatSession, PanelData, ToolCallEvent } from "@/types";
import { fetchSessions, fetchSessionMessages } from "@/services/api";

const STORAGE_KEY = "gas-copilot-chat";

interface ChatState {
  sessions: ChatSession[];
  currentSessionId: string;
  messagesMap: Record<string, ChatMessage[]>;
  isStreaming: boolean;
  sidebarOpen: boolean;

  hydrateFromServer: () => Promise<void>;

  createSession: () => string;
  switchSession: (id: string) => void;
  deleteSession: (id: string) => void;

  addMessage: (msg: ChatMessage) => void;
  appendToLastAssistant: (content: string) => void;
  addToolCallToLast: (tc: ToolCallEvent) => void;
  updateToolCallInLast: (name: string, update: Partial<ToolCallEvent>) => void;
  addPanelDataToLast: (pd: PanelData) => void;

  setStreaming: (s: boolean) => void;
  toggleSidebar: () => void;
}

function makeSessionId(): string {
  return `s-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      sessions: [],
      currentSessionId: "",
      messagesMap: {},
      isStreaming: false,
      sidebarOpen: true,

      hydrateFromServer: async () => {
        try {
          const { sessions } = await fetchSessions();
          if (!sessions?.length) return;
          const messagesMap: Record<string, ChatMessage[]> = {};
          for (const s of sessions) {
            const data = await fetchSessionMessages(s.id);
            messagesMap[s.id] = (data.messages ?? []) as ChatMessage[];
          }
          set({
            sessions,
            messagesMap,
            currentSessionId: sessions[0].id,
          });
        } catch {
          /* offline or API unavailable — keep persisted local state */
        }
      },

      createSession: () => {
    const id = makeSessionId();
    const session: ChatSession = {
      id,
      title: "新对话",
      createdAt: Date.now(),
      updatedAt: Date.now(),
    };
    set((s) => ({
      sessions: [session, ...s.sessions],
      currentSessionId: id,
      messagesMap: { ...s.messagesMap, [id]: [] },
    }));
        return id;
      },

      switchSession: (id) => set({ currentSessionId: id }),

      deleteSession: (id) =>
    set((s) => {
      const sessions = s.sessions.filter((ss) => ss.id !== id);
      const map = { ...s.messagesMap };
      delete map[id];
      const next = sessions[0]?.id ?? "";
      return {
        sessions,
        messagesMap: map,
        currentSessionId: s.currentSessionId === id ? next : s.currentSessionId,
        };
      }),

      addMessage: (msg) =>
    set((s) => {
      const sid = s.currentSessionId;
      const msgs = [...(s.messagesMap[sid] ?? []), msg];
      const sessions = s.sessions.map((ss) =>
        ss.id === sid
          ? {
              ...ss,
              updatedAt: Date.now(),
              title:
                ss.title === "新对话" && msg.role === "user"
                  ? msg.content.slice(0, 24) + (msg.content.length > 24 ? "..." : "")
                  : ss.title,
            }
          : ss,
      );
        return { messagesMap: { ...s.messagesMap, [sid]: msgs }, sessions };
      }),

      appendToLastAssistant: (content) =>
    set((s) => {
      const sid = s.currentSessionId;
      const msgs = [...(s.messagesMap[sid] ?? [])];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant") {
        msgs[msgs.length - 1] = { ...last, content: last.content + content };
      }
        return { messagesMap: { ...s.messagesMap, [sid]: msgs } };
      }),

      addToolCallToLast: (tc) =>
    set((s) => {
      const sid = s.currentSessionId;
      const msgs = [...(s.messagesMap[sid] ?? [])];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant") {
        msgs[msgs.length - 1] = {
          ...last,
          toolCalls: [...(last.toolCalls ?? []), tc],
        };
      }
        return { messagesMap: { ...s.messagesMap, [sid]: msgs } };
      }),

      updateToolCallInLast: (name, update) =>
    set((s) => {
      const sid = s.currentSessionId;
      const msgs = [...(s.messagesMap[sid] ?? [])];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant" && last.toolCalls) {
        const idx = [...last.toolCalls].reverse().findIndex((t) => t.name === name && t.status === "running");
        if (idx !== -1) {
          const realIdx = last.toolCalls.length - 1 - idx;
          const updated = [...last.toolCalls];
          updated[realIdx] = { ...updated[realIdx], ...update };
          msgs[msgs.length - 1] = { ...last, toolCalls: updated };
        }
      }
        return { messagesMap: { ...s.messagesMap, [sid]: msgs } };
      }),

      addPanelDataToLast: (pd) =>
    set((s) => {
      const sid = s.currentSessionId;
      const msgs = [...(s.messagesMap[sid] ?? [])];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant") {
        msgs[msgs.length - 1] = {
          ...last,
          panelData: [...(last.panelData ?? []), pd],
        };
      }
        return { messagesMap: { ...s.messagesMap, [sid]: msgs } };
      }),

      setStreaming: (isStreaming) => set({ isStreaming }),
      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
    }),
    {
      name: STORAGE_KEY,
      partialize: (s) => ({
        sessions: s.sessions,
        currentSessionId: s.currentSessionId,
        messagesMap: s.messagesMap,
        sidebarOpen: s.sidebarOpen,
      }),
      merge: (persisted, current) => {
        const p = persisted as Partial<ChatState> | undefined;
        return {
          ...current,
          ...p,
          isStreaming: false,
        };
      },
    },
  ),
);
