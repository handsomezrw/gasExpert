import { useOverlayStore } from "@/stores/overlayStore";

interface Props {
  showLabel?: boolean;
}

const STATUS_CONFIG = {
  pending: { icon: "⏳", bg: "bg-amber-50", text: "text-amber-700", label: "同步中" },
  synced: { icon: "✅", bg: "bg-green-50", text: "text-green-700", label: "已同步" },
  failed: { icon: "❌", bg: "bg-red-50", text: "text-red-700", label: "同步失败" },
} as const;

export function MapSyncStatus({ showLabel = true }: Props) {
  const overlays = useOverlayStore((s) => s.overlays);

  if (overlays.length === 0) return null;

  const latest = overlays[overlays.length - 1];
  const config = STATUS_CONFIG[latest.status];

  return (
    <div className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs ${config.bg} ${config.text}`}>
      <span>{config.icon}</span>
      {showLabel && (
        <span>
          {config.label}
          {latest.layerType === "evacuation_zone" && " 疏散圈" }
          {latest.layerType === "valve_isolation" && " 关阀方案" }
          {latest.layerType === "repair_plan" && " 抢修方案" }
        </span>
      )}
    </div>
  );
}
