import { ShieldAlert, MapPin, Wind } from "lucide-react";

interface Props {
  data: Record<string, unknown>;
}

const RISK_THEME: Record<string, { bg: string; text: string; border: string }> = {
  "高危": { bg: "bg-red-50", text: "text-red-700", border: "border-red-200" },
  "中危": { bg: "bg-amber-50", text: "text-amber-700", border: "border-amber-200" },
  "低危": { bg: "bg-green-50", text: "text-green-700", border: "border-green-200" },
};

export function EvacuationPanel({ data }: Props) {
  const radius = data.radius_m as number ?? 0;
  const area = data.affected_area_m2 as number ?? 0;
  const riskLevel = data.risk_level as string ?? "未知";
  const pressureClass = data.pressure_class as string ?? "";
  const leakType = data.leak_type as string ?? "";
  const instructions = (data.safety_instructions as string[]) ?? [];

  const theme = RISK_THEME[riskLevel] ?? RISK_THEME["中危"];

  return (
    <div className={`rounded-xl border ${theme.border} ${theme.bg} p-4`}>
      <div className="mb-3 flex items-center gap-2">
        <ShieldAlert className={`h-5 w-5 ${theme.text}`} />
        <h3 className={`text-sm font-semibold ${theme.text}`}>疏散范围计算结果</h3>
      </div>

      {/* Key metrics */}
      <div className="mb-4 grid grid-cols-3 gap-3">
        <MetricCard
          label="疏散半径"
          value={`${radius.toFixed(1)}`}
          unit="m"
          icon={<MapPin className="h-4 w-4" />}
        />
        <MetricCard
          label="影响面积"
          value={area > 1000 ? `${(area / 1000).toFixed(1)}k` : area.toFixed(0)}
          unit="m²"
          icon={<Wind className="h-4 w-4" />}
        />
        <div className={`flex flex-col items-center justify-center rounded-lg border ${theme.border} bg-white/60 p-3`}>
          <span className={`text-xl font-bold ${theme.text}`}>{riskLevel}</span>
          <span className="text-[10px] text-muted-foreground">风险等级</span>
        </div>
      </div>

      {/* Details */}
      {(pressureClass || leakType) && (
        <div className="mb-3 flex gap-2 text-xs">
          {pressureClass && (
            <span className="rounded-full bg-white/70 px-2 py-0.5 text-muted-foreground">
              压力等级: {pressureClass}
            </span>
          )}
          {leakType && (
            <span className="rounded-full bg-white/70 px-2 py-0.5 text-muted-foreground">
              泄漏类型: {leakType === "rupture" ? "管道破裂" : leakType}
            </span>
          )}
        </div>
      )}

      {/* Safety instructions */}
      {instructions.length > 0 && (
        <div className="rounded-lg bg-white/50 p-3">
          <p className="mb-1.5 text-xs font-medium text-foreground/80">安全措施</p>
          <ol className="space-y-1 text-xs text-muted-foreground">
            {instructions.map((item, i) => (
              <li key={i} className="flex gap-2">
                <span className="shrink-0 font-mono text-muted-foreground/60">{i + 1}.</span>
                {item}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  unit,
  icon,
}: {
  label: string;
  value: string;
  unit: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center rounded-lg border border-white/50 bg-white/60 p-3">
      <div className="mb-1 text-muted-foreground/60">{icon}</div>
      <div className="flex items-baseline gap-0.5">
        <span className="text-lg font-bold text-foreground">{value}</span>
        <span className="text-[10px] text-muted-foreground">{unit}</span>
      </div>
      <span className="text-[10px] text-muted-foreground">{label}</span>
    </div>
  );
}
