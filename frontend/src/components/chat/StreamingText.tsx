import { MarkdownContent } from "./MarkdownContent";

interface Props {
  text: string;
}

export function StreamingText({ text }: Props) {
  return (
    <div className="relative">
      <MarkdownContent content={text} />
      <span className="inline-block w-2 h-4 ml-0.5 animate-pulse bg-foreground/50 rounded-sm align-text-bottom" />
    </div>
  );
}
