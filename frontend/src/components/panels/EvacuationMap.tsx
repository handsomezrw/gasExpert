interface Props {
  radiusM: number;
  affectedAreaM2: number;
  riskLevel: string;
}

const RISK_COLORS: Record<string, string> = {
  高危: "text-red-600 bg-red-50",
  中危: "text-amber-600 bg-amber-50",
  低危: "text-green-600 bg-green-50",
};

export function EvacuationMap({ radiusM, affectedAreaM2, riskLevel }: Props) {
  const colorClass = RISK_COLORS[riskLevel] ?? "text-foreground bg-muted";

  return (
    <div className="rounded-md border bg-card p-4 space-y-2">
      <h3 className="text-sm font-semibold">疏散范围计算</h3>
      <div className="grid grid-cols-3 gap-3 text-center text-sm">
        <div className="rounded-md bg-muted p-3">
          <p className="text-2xl font-bold">{radiusM}</p>
          <p className="text-xs text-muted-foreground">半径 (m)</p>
        </div>
        <div className="rounded-md bg-muted p-3">
          <p className="text-2xl font-bold">{affectedAreaM2.toLocaleString()}</p>
          <p className="text-xs text-muted-foreground">面积 (m²)</p>
        </div>
        <div className={`rounded-md p-3 ${colorClass}`}>
          <p className="text-2xl font-bold">{riskLevel}</p>
          <p className="text-xs">风险等级</p>
        </div>
      </div>
    </div>
  );
}
