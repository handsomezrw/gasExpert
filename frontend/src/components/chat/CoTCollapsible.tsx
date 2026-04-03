import { useState } from "react";
import type { ToolCallEvent } from "@/types";

interface Props {
  toolCalls: ToolCallEvent[];
}

const STATUS_ICON: Record<string, string> = {
  pending: "⏳",
  running: "⚙️",
  done: "✅",
  error: "❌",
};

export function CoTCollapsible({ toolCalls }: Props) {
  const [open, setOpen] = useState(true);

  return (
    <div className="rounded-md border bg-card text-card-foreground text-sm">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2 font-medium hover:bg-accent/50"
      >
        <span className={`transition-transform ${open ? "rotate-90" : ""}`}>
          ▶
        </span>
        思维链 ({toolCalls.length} 步)
      </button>
      {open && (
        <div className="border-t px-3 py-2 space-y-1.5">
          {toolCalls.map((tc) => (
            <div key={tc.id} className="flex items-start gap-2 text-xs">
              <span>{STATUS_ICON[tc.status] ?? "❓"}</span>
              <div>
                <span className="font-mono font-medium">{tc.name}</span>
                <span className="ml-1 text-muted-foreground">
                  {JSON.stringify(tc.args)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
