import { useState } from "react";
import {
  ChevronDown,
  Brain,
  Wrench,
  Search,
  CheckCircle2,
  XCircle,
  Loader2,
} from "lucide-react";
import type { ToolCallEvent } from "@/types";

interface Props {
  toolCalls: ToolCallEvent[];
}

const ICON_MAP: Record<string, typeof Brain> = {
  planner: Brain,
  reflector: CheckCircle2,
  knowledge_search: Search,
};

const LABEL_MAP: Record<string, string> = {
  planner: "规划分析",
  reflector: "结果评估",
  knowledge_search: "知识检索",
  calculate_evacuation_zone: "疏散范围计算",
  query_material_inventory: "物资库存查询",
  get_weather_info: "天气信息获取",
  consult_gas_expert: "燃气专家咨询",
  generate_report: "报告生成",
};

export function CoTSteps({ toolCalls }: Props) {
  const [open, setOpen] = useState(false);

  if (!toolCalls.length) return null;

  const doneCount = toolCalls.filter((t) => t.status === "done").length;
  const hasRunning = toolCalls.some((t) => t.status === "running");

  return (
    <div className="mb-3">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      >
        {hasRunning ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
        )}
        <span>
          {hasRunning
            ? `正在处理... (${doneCount}/${toolCalls.length})`
            : `已完成 ${doneCount} 个步骤`}
        </span>
        <ChevronDown
          className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="ml-1 mt-1.5 border-l-2 border-border pl-4 space-y-2">
          {toolCalls.map((tc) => (
            <StepItem key={tc.id} step={tc} />
          ))}
        </div>
      )}
    </div>
  );
}

function StepItem({ step }: { step: ToolCallEvent }) {
  const [expanded, setExpanded] = useState(false);
  const Icon = ICON_MAP[step.name] ?? Wrench;
  const label = LABEL_MAP[step.name] ?? step.name;

  return (
    <div className="text-xs">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 py-0.5 text-left hover:text-foreground"
      >
        <StatusDot status={step.status} />
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="font-medium">{label}</span>
        {step.name === "planner" && !!step.result && (
          <span className="rounded bg-accent px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {(step.result as Record<string, string>).decision}
          </span>
        )}
        {Object.keys(step.args ?? {}).length > 0 && (
          <ChevronDown
            className={`h-3 w-3 text-muted-foreground transition-transform ${expanded ? "rotate-180" : ""}`}
          />
        )}
      </button>

      {expanded && (
        <div className="ml-6 mt-1 space-y-1 rounded bg-muted/50 p-2 font-mono text-[11px] text-muted-foreground">
          {Object.keys(step.args ?? {}).length > 0 && (
            <div>
              <span className="font-medium text-foreground/70">参数: </span>
              <span>{JSON.stringify(step.args, null, 2)}</span>
            </div>
          )}
          {!!step.result && step.name !== "planner" && step.name !== "reflector" && (
            <div>
              <span className="font-medium text-foreground/70">结果: </span>
              <span>
                {typeof step.result === "string"
                  ? step.result
                  : JSON.stringify(step.result, null, 2)}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  if (status === "running")
    return <Loader2 className="h-3 w-3 animate-spin text-blue-500" />;
  if (status === "done")
    return <CheckCircle2 className="h-3 w-3 text-green-500" />;
  if (status === "error")
    return <XCircle className="h-3 w-3 text-red-500" />;
  return <div className="h-3 w-3 rounded-full border border-muted-foreground" />;
}
