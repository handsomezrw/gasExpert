import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  content: string;
}

export function MarkdownContent({ content }: Props) {
  return (
    <div className="markdown-body">
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        table: ({ children, ...props }) => (
          <div className="my-3 overflow-x-auto">
            <table
              className="min-w-full border-collapse text-sm"
              {...props}
            >
              {children}
            </table>
          </div>
        ),
        thead: ({ children, ...props }) => (
          <thead className="bg-muted/60" {...props}>
            {children}
          </thead>
        ),
        th: ({ children, ...props }) => (
          <th
            className="border border-border px-3 py-1.5 text-left font-medium text-foreground"
            {...props}
          >
            {children}
          </th>
        ),
        td: ({ children, ...props }) => (
          <td
            className="border border-border px-3 py-1.5 text-muted-foreground"
            {...props}
          >
            {children}
          </td>
        ),
        code: ({ children, className, ...props }) => {
          const isBlock = className?.includes("language-");
          if (isBlock) {
            return (
              <pre className="my-3 overflow-x-auto rounded-lg bg-[#1e1e1e] p-4 text-sm text-gray-100">
                <code className={className} {...props}>
                  {children}
                </code>
              </pre>
            );
          }
          return (
            <code
              className="rounded bg-muted px-1.5 py-0.5 text-sm font-mono text-foreground"
              {...props}
            >
              {children}
            </code>
          );
        },
      }}
    >
      {content}
    </ReactMarkdown>
    </div>
  );
}
