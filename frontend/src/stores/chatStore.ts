import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ChatMessage, ChatSession, PanelData, ToolCallEvent } from "@/types";

const STORAGE_KEY = "gas-copilot-chat";

interface ChatState {
  sessions: ChatSession[];
  currentSessionId: string;
  messagesMap: Record<string, ChatMessage[]>;
  isStreaming: boolean;
  sidebarOpen: boolean;

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

const MOCK_SESSIONS: ChatSession[] = [
  {
    id: "mock-1",
    title: "武侯区燃气泄漏应急处置",
    createdAt: Date.now() - 3600_000,
    updatedAt: Date.now() - 3600_000,
  },
  {
    id: "mock-2",
    title: "高新区管道破裂疏散方案",
    createdAt: Date.now() - 86400_000,
    updatedAt: Date.now() - 86400_000,
  },
];

const MOCK_MESSAGES: Record<string, ChatMessage[]> = {
  "mock-1": [
    {
      id: "m1",
      role: "user",
      content: "成都武侯区发生天然气泄漏，管径DN200，压力0.4MPa，请计算疏散范围",
      timestamp: Date.now() - 3600_000,
    },
    {
      id: "m2",
      role: "assistant",
      content:
        "根据您提供的参数，我已为您计算疏散范围：\n\n" +
        "**关键数据**\n" +
        "- **疏散半径**：31.3 米\n" +
        "- **影响面积**：约 3,078.8 平方米\n" +
        "- **风险等级**：高危（中压A级管道破裂泄漏）\n\n" +
        "### 安全措施建议\n" +
        "1. **立即启动应急响应**\n" +
        "2. **设置警戒区域** — 在泄漏点为圆心、半径 31.3 米的范围内设置警戒\n" +
        "3. **切断气源** — 关闭泄漏点上下游阀门\n" +
        "4. **通风散气** — 如在室内需立即开窗通风\n\n" +
        "| 项目 | 数值 |\n" +
        "| :--- | :--- |\n" +
        "| 疏散半径 | 31.3 m |\n" +
        "| 影响面积 | 3,078.8 m² |\n" +
        "| 压力等级 | 中压A |\n" +
        "| 泄漏类型 | 管道破裂 |",
      timestamp: Date.now() - 3590_000,
      toolCalls: [
        {
          id: "tc1",
          name: "planner",
          args: {},
          result: { decision: "use_tools", reasoning: "用户要求计算疏散范围，需要使用疏散计算工具" },
          status: "done",
          timestamp: Date.now() - 3595_000,
        },
        {
          id: "tc2",
          name: "calculate_evacuation_zone",
          args: { pressure: 0.4, diameter: 200, leak_type: "rupture" },
          result: { radius_m: 31.3, affected_area_m2: 3078.8, risk_level: "高危" },
          status: "done",
          timestamp: Date.now() - 3593_000,
        },
        {
          id: "tc3",
          name: "reflector",
          args: {},
          result: { verdict: "sufficient" },
          status: "done",
          timestamp: Date.now() - 3592_000,
        },
      ],
      panelData: [
        {
          type: "evacuation",
          data: {
            radius_m: 31.3,
            affected_area_m2: 3078.8,
            risk_level: "高危",
            risk_color: "red",
            pressure_class: "中压A",
            leak_type: "rupture",
            safety_instructions: [
              "立即启动应急响应",
              "设置警戒区域",
              "切断气源",
              "通风散气",
            ],
          },
        },
      ],
    },
  ],
  "mock-2": [
    {
      id: "m3",
      role: "user",
      content: "查询高新区附近的应急物资库存情况",
      timestamp: Date.now() - 86400_000,
    },
    {
      id: "m4",
      role: "assistant",
      content:
        "已为您查询到高新区附近的应急物资站点：\n\n" +
        "**最近站点**：高新区应急物资站（距离 2.3km）\n\n" +
        "| 物资名称 | 库存数量 | 状态 |\n" +
        "| :--- | :--- | :--- |\n" +
        "| PE管抢修夹具 | 15 套 | 充足 |\n" +
        "| 堵漏气囊 | 8 个 | 充足 |\n" +
        "| 可燃气体检测仪 | 5 台 | 正常 |\n" +
        "| 防爆风机 | 3 台 | 正常 |",
      timestamp: Date.now() - 86390_000,
      toolCalls: [
        {
          id: "tc4",
          name: "planner",
          args: {},
          result: { decision: "use_tools", reasoning: "需要查询物资库存" },
          status: "done",
          timestamp: Date.now() - 86395_000,
        },
        {
          id: "tc5",
          name: "query_material_inventory",
          args: { location: "高新区", radius_km: 10 },
          result: { matched_stations: 3 },
          status: "done",
          timestamp: Date.now() - 86393_000,
        },
      ],
      panelData: [
        {
          type: "inventory",
          data: {
            query_location: "高新区",
            search_radius_km: 10,
            matched_stations: 3,
            stations: [
              {
                station_name: "高新区应急物资站",
                distance_km: 2.3,
                materials: [
                  { name: "PE管抢修夹具", quantity: 15, unit: "套" },
                  { name: "堵漏气囊", quantity: 8, unit: "个" },
                  { name: "可燃气体检测仪", quantity: 5, unit: "台" },
                  { name: "防爆风机", quantity: 3, unit: "台" },
                ],
              },
              {
                station_name: "天府新区备用仓库",
                distance_km: 5.8,
                materials: [
                  { name: "PE管抢修夹具", quantity: 20, unit: "套" },
                  { name: "堵漏气囊", quantity: 12, unit: "个" },
                ],
              },
            ],
          },
        },
      ],
    },
  ],
};

function makeSessionId(): string {
  return `s-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      sessions: [...MOCK_SESSIONS],
      currentSessionId: MOCK_SESSIONS[0].id,
      messagesMap: { ...MOCK_MESSAGES },
      isStreaming: false,
      sidebarOpen: true,

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
