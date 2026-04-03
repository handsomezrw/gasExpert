import type { PanelData, ToolCallEvent } from "@/types";

interface StreamChatOptions {
  message: string;
  sessionId: string;
  onToken: (token: string) => void;
  onToolStart: (tc: ToolCallEvent) => void;
  onToolEnd: (tc: ToolCallEvent) => void;
  onPanelData: (data: PanelData) => void;
  onError?: (error: string) => void;
  onDone?: () => void;
}

export async function streamChat({
  message,
  sessionId,
  onToken,
  onToolStart,
  onToolEnd,
  onPanelData,
  onError,
  onDone,
}: StreamChatOptions) {
  let doneReceived = false;

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    });

    if (!response.ok) {
      onError?.(`HTTP ${response.status}`);
      return;
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let currentEvent = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) {
          currentEvent = "";
          continue;
        }
        if (trimmed.startsWith("event:")) {
          currentEvent = trimmed.slice(6).trim();
        } else if (trimmed.startsWith("data:")) {
          const raw = trimmed.slice(5).trim();
          try {
            const data = JSON.parse(raw);
            switch (currentEvent) {
              case "token":
                onToken(data.content ?? "");
                break;
              case "tool_start":
                onToolStart({
                  id: data.id,
                  name: data.name,
                  args: data.args ?? {},
                  result: data.result,
                  status: data.status ?? "running",
                  timestamp: data.timestamp ?? Date.now(),
                });
                break;
              case "tool_end":
                onToolEnd({
                  id: data.id,
                  name: data.name,
                  args: data.args ?? {},
                  result: data.result,
                  status: data.status ?? "done",
                  timestamp: data.timestamp ?? Date.now(),
                });
                break;
              case "panel_data":
                onPanelData(data as PanelData);
                break;
              case "error":
                onError?.(data.message ?? "Unknown error");
                break;
              case "done":
                doneReceived = true;
                onDone?.();
                break;
            }
          } catch {
            /* skip malformed JSON */
          }
        }
      }
    }
  } catch (err) {
    onError?.(err instanceof Error ? err.message : String(err));
  }

  if (!doneReceived) onDone?.();
}
