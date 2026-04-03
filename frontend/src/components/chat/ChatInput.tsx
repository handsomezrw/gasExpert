import { useRef, useState, type KeyboardEvent, type FormEvent } from "react";
import { Send } from "lucide-react";

interface Props {
  onSend: (message: string) => void;
  disabled?: boolean;
}

export function ChatInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const adjustHeight = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  const handleSubmit = (e?: FormEvent) => {
    e?.preventDefault();
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="border-t bg-background px-4 py-3">
      <form
        onSubmit={handleSubmit}
        className="mx-auto flex max-w-3xl items-end gap-3 rounded-2xl border bg-muted/40 px-4 py-2.5 shadow-sm transition-shadow focus-within:shadow-md focus-within:border-ring/50"
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            adjustHeight();
          }}
          onKeyDown={handleKeyDown}
          placeholder="描述抢险情况或提出问题..."
          disabled={disabled}
          rows={1}
          className="flex-1 resize-none bg-transparent text-sm leading-6 outline-none placeholder:text-muted-foreground disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          <Send className="h-4 w-4" />
        </button>
      </form>
      <p className="mx-auto mt-2 max-w-3xl text-center text-xs text-muted-foreground">
        燃气抢险智能副驾可能会产生错误信息，请以实际规范为准
      </p>
    </div>
  );
}
