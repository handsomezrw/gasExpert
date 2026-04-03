export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  toolCalls?: ToolCallEvent[];
  panelData?: PanelData[];
}

export interface ToolCallEvent {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
  status: "running" | "done" | "error";
  timestamp: number;
}

export interface PanelData {
  type: "evacuation" | "inventory" | "weather" | "report";
  data: Record<string, unknown>;
}

export interface SSEEvent {
  event: "token" | "tool_start" | "tool_end" | "panel_data" | "error" | "done";
  data: string;
}

export interface ChatSession {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
}
