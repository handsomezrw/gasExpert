import { FileText, Download } from "lucide-react";
import { MarkdownContent } from "@/components/chat/MarkdownContent";

interface Props {
  data: Record<string, unknown>;
}

export function ReportPanel({ data }: Props) {
  const content =
    typeof data === "string"
      ? data
      : (data.content as string) ?? (data.report as string) ?? "";

  if (!content) return null;

  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileText className="h-5 w-5 text-emerald-600" />
          <h3 className="text-sm font-semibold text-emerald-700">
            应急处置报告
          </h3>
        </div>
        <button
          onClick={() => {
            const blob = new Blob([content], { type: "text/markdown" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `应急报告_${new Date().toISOString().slice(0, 10)}.md`;
            a.click();
            URL.revokeObjectURL(url);
          }}
          className="flex items-center gap-1 rounded-lg bg-emerald-100 px-2 py-1 text-xs text-emerald-700 transition-colors hover:bg-emerald-200"
        >
          <Download className="h-3 w-3" />
          下载
        </button>
      </div>

      <div className="rounded-lg bg-white/70 p-4 text-sm">
        <MarkdownContent content={content} />
      </div>
    </div>
  );
}
