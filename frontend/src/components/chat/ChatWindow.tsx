import { useEffect, useRef } from "react";
import { Flame } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";
import { streamChat } from "@/services/sse";
import { MessageItem } from "./MessageItem";
import { ChatInput } from "./ChatInput";
import type { ChatMessage } from "@/types";

const SUGGESTIONS = [
  { icon: "📏", title: "计算疏散范围", text: "成都武侯区发生天然气泄漏，管径DN200，压力0.4MPa，请计算疏散范围" },
  { icon: "📦", title: "查询物资库存", text: "查询武侯区附近的应急物资库存情况" },
  { icon: "🌤️", title: "查询天气信息", text: "查询成都武侯区当前天气，评估对燃气泄漏处置的影响" },
  { icon: "📋", title: "生成处置报告", text: "根据武侯区燃气泄漏事故生成应急处置报告" },
];

export function ChatWindow() {
  const scrollRef = useRef<HTMLDivElement>(null);

  const currentSessionId = useChatStore((s) => s.currentSessionId);
  const messages = useChatStore(
    (s) => s.messagesMap[s.currentSessionId] ?? [],
  );
  const isStreaming = useChatStore((s) => s.isStreaming);
  const addMessage = useChatStore((s) => s.addMessage);
  const appendToLastAssistant = useChatStore((s) => s.appendToLastAssistant);
  const addToolCallToLast = useChatStore((s) => s.addToolCallToLast);
  const updateToolCallInLast = useChatStore((s) => s.updateToolCallInLast);
  const addPanelDataToLast = useChatStore((s) => s.addPanelDataToLast);
  const setStreaming = useChatStore((s) => s.setStreaming);
  const createSession = useChatStore((s) => s.createSession);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const handleSend = async (text: string) => {
    if (isStreaming) return;

    let sid = currentSessionId;
    if (!sid || messages.length === 0 && !useChatStore.getState().sessions.find((s) => s.id === sid)) {
      sid = createSession();
    }

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      timestamp: Date.now(),
    };
    addMessage(userMsg);

    const assistantMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "",
      timestamp: Date.now(),
    };
    addMessage(assistantMsg);
    setStreaming(true);

    await streamChat({
      message: text,
      sessionId: sid,
      onToken: (token) => appendToLastAssistant(token),
      onToolStart: (tc) => {
        if (tc.status === "done") {
          addToolCallToLast(tc);
        } else {
          addToolCallToLast(tc);
        }
      },
      onToolEnd: (tc) => {
        updateToolCallInLast(tc.name, {
          status: tc.status,
          result: tc.result,
          timestamp: tc.timestamp,
        });
      },
      onPanelData: (pd) => addPanelDataToLast(pd),
      onError: (err) => appendToLastAssistant(`\n\n> ⚠️ 错误: ${err}`),
      onDone: () => setStreaming(false),
    });

    setStreaming(false);
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <EmptyState onSelect={handleSend} />
        ) : (
          <div className="pb-4">
            {messages.map((msg, i) => (
              <MessageItem
                key={msg.id}
                message={msg}
                isStreaming={isStreaming}
                isLast={i === messages.length - 1}
              />
            ))}
          </div>
        )}
      </div>
      <ChatInput onSend={handleSend} disabled={isStreaming} />
    </div>
  );
}

function EmptyState({ onSelect }: { onSelect: (text: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-4">
      <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-amber-100">
        <Flame className="h-8 w-8 text-amber-600" />
      </div>
      <h2 className="mb-2 text-xl font-semibold">燃气抢险智能副驾</h2>
      <p className="mb-8 max-w-md text-center text-sm text-muted-foreground">
        我可以帮您计算疏散范围、查询物资库存、获取天气信息、生成处置报告、咨询燃气专业技术问题
      </p>
      <div className="grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s.title}
            onClick={() => onSelect(s.text)}
            className="flex items-start gap-3 rounded-xl border bg-card p-4 text-left transition-colors hover:bg-accent"
          >
            <span className="text-lg">{s.icon}</span>
            <div>
              <p className="text-sm font-medium">{s.title}</p>
              <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">
                {s.text}
              </p>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
