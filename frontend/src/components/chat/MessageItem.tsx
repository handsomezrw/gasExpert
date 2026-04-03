import { Flame, User } from "lucide-react";
import type { ChatMessage } from "@/types";
import { MarkdownContent } from "./MarkdownContent";
import { StreamingText } from "./StreamingText";
import { CoTSteps } from "./CoTSteps";
import { PanelRenderer } from "@/components/panels/PanelRenderer";

interface Props {
  message: ChatMessage;
  isStreaming?: boolean;
  isLast?: boolean;
}

export function MessageItem({ message, isStreaming, isLast }: Props) {
  const isUser = message.role === "user";
  const showCursor = isLast && isStreaming && !isUser;

  return (
    <div className="group py-5">
      <div className="mx-auto flex max-w-3xl gap-4 px-4">
        {/* Avatar */}
        <div
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
            isUser
              ? "bg-primary/10 text-primary"
              : "bg-amber-100 text-amber-600"
          }`}
        >
          {isUser ? <User className="h-4 w-4" /> : <Flame className="h-4 w-4" />}
        </div>

        {/* Content */}
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            {isUser ? "你" : "智能副驾"}
          </p>

          {isUser ? (
            <p className="text-sm leading-relaxed whitespace-pre-wrap">
              {message.content}
            </p>
          ) : (
            <div className="text-sm leading-relaxed">
              {/* CoT Steps */}
              {message.toolCalls && message.toolCalls.length > 0 && (
                <CoTSteps toolCalls={message.toolCalls} />
              )}

              {/* Message content */}
              {message.content ? (
                showCursor ? (
                  <StreamingText text={message.content} />
                ) : (
                  <MarkdownContent content={message.content} />
                )
              ) : (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <div className="flex gap-1">
                    <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/40 [animation-delay:0ms]" />
                    <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/40 [animation-delay:150ms]" />
                    <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/40 [animation-delay:300ms]" />
                  </div>
                  <span className="text-xs">思考中...</span>
                </div>
              )}

              {/* Business panels */}
              {message.panelData && message.panelData.length > 0 && (
                <PanelRenderer panels={message.panelData} />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
