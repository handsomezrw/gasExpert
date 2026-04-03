import type { PanelData } from "@/types";
import { EvacuationPanel } from "./EvacuationPanel";
import { InventoryPanel } from "./InventoryPanel";
import { WeatherPanel } from "./WeatherPanel";
import { ReportPanel } from "./ReportPanel";

interface Props {
  panels: PanelData[];
}

export function PanelRenderer({ panels }: Props) {
  if (!panels.length) return null;

  return (
    <div className="mt-3 space-y-3">
      {panels.map((panel, i) => (
        <div key={`${panel.type}-${i}`}>
          {panel.type === "evacuation" && <EvacuationPanel data={panel.data} />}
          {panel.type === "inventory" && <InventoryPanel data={panel.data} />}
          {panel.type === "weather" && <WeatherPanel data={panel.data} />}
          {panel.type === "report" && <ReportPanel data={panel.data} />}
        </div>
      ))}
    </div>
  );
}
