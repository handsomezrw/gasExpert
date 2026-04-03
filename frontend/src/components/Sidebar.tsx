import { Plus, MessageSquare, Trash2 } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";
import type { ChatSession } from "@/types";

export function Sidebar() {
  const sessions = useChatStore((s) => s.sessions);
  const currentSessionId = useChatStore((s) => s.currentSessionId);
  const switchSession = useChatStore((s) => s.switchSession);
  const createSession = useChatStore((s) => s.createSession);
  const deleteSession = useChatStore((s) => s.deleteSession);
  const sidebarOpen = useChatStore((s) => s.sidebarOpen);

  const grouped = groupByDate(sessions);

  if (!sidebarOpen) return null;

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r bg-secondary/30">
      {/* New Chat */}
      <div className="p-3">
        <button
          onClick={() => createSession()}
          className="flex w-full items-center gap-2 rounded-lg border bg-background px-3 py-2.5 text-sm font-medium transition-colors hover:bg-accent"
        >
          <Plus className="h-4 w-4" />
          新建对话
        </button>
      </div>

      {/* Session list */}
      <nav className="flex-1 overflow-y-auto px-2 pb-3">
        {grouped.map(([label, items]) => (
          <div key={label} className="mb-3">
            <p className="px-2 py-1.5 text-xs font-medium text-muted-foreground">
              {label}
            </p>
            {items.map((session) => (
              <SessionItem
                key={session.id}
                session={session}
                active={session.id === currentSessionId}
                onSelect={() => switchSession(session.id)}
                onDelete={() => deleteSession(session.id)}
              />
            ))}
          </div>
        ))}
      </nav>
    </aside>
  );
}

function SessionItem({
  session,
  active,
  onSelect,
  onDelete,
}: {
  session: ChatSession;
  active: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      className={`group flex items-center gap-2 rounded-lg px-2 py-2 text-sm cursor-pointer transition-colors ${
        active ? "bg-accent font-medium" : "hover:bg-accent/50"
      }`}
      onClick={onSelect}
    >
      <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="flex-1 truncate">{session.title}</span>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        className="hidden shrink-0 rounded p-0.5 text-muted-foreground hover:text-destructive group-hover:block"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function groupByDate(sessions: ChatSession[]): [string, ChatSession[]][] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const yesterday = today - 86400_000;
  const weekAgo = today - 7 * 86400_000;

  const groups: Record<string, ChatSession[]> = {};

  for (const s of sessions) {
    let label: string;
    if (s.updatedAt >= today) label = "今天";
    else if (s.updatedAt >= yesterday) label = "昨天";
    else if (s.updatedAt >= weekAgo) label = "近7天";
    else label = "更早";

    (groups[label] ??= []).push(s);
  }

  const order = ["今天", "昨天", "近7天", "更早"];
  return order.filter((k) => groups[k]?.length).map((k) => [k, groups[k]]);
}
