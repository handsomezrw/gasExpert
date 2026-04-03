import { Package, MapPin } from "lucide-react";

interface MaterialItem {
  name: string;
  quantity: number;
  unit?: string;
  spec?: string;
}

interface Station {
  station_name: string;
  distance_km: number;
  materials?: MaterialItem[];
  items?: MaterialItem[];
}

interface Props {
  data: Record<string, unknown>;
}

export function InventoryPanel({ data }: Props) {
  const rawStations = (data.stations as Station[]) ?? [];
  const stations = rawStations.map((s) => ({
    ...s,
    materials: s.materials ?? s.items ?? [],
  }));
  const queryLocation = data.query_location as string ?? "";
  const matchedCount = data.matched_stations as number ?? stations.length;

  if (!stations.length) return null;

  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Package className="h-5 w-5 text-blue-600" />
          <h3 className="text-sm font-semibold text-blue-700">应急物资库存</h3>
        </div>
        {queryLocation && (
          <span className="flex items-center gap-1 text-xs text-blue-600/70">
            <MapPin className="h-3 w-3" />
            {queryLocation}附近 · {matchedCount} 个站点
          </span>
        )}
      </div>

      <div className="space-y-3">
        {stations.map((station) => (
          <div
            key={station.station_name}
            className="rounded-lg bg-white/60 p-3"
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium text-foreground">
                {station.station_name}
              </span>
              <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] text-blue-700">
                {station.distance_km} km
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="pb-1 font-medium">物资名称</th>
                    <th className="pb-1 text-right font-medium">库存</th>
                    <th className="pb-1 text-right font-medium">状态</th>
                  </tr>
                </thead>
                <tbody>
                  {station.materials.map((m) => (
                    <tr key={m.name} className="border-t border-blue-100/50">
                      <td className="py-1 text-foreground">{m.name}</td>
                      <td className="py-1 text-right text-muted-foreground">
                        {m.quantity} {m.unit ?? ""}
                      </td>
                      <td className="py-1 text-right">
                        <StatusBadge quantity={m.quantity} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StatusBadge({ quantity }: { quantity: number }) {
  if (quantity >= 10) {
    return (
      <span className="rounded-full bg-green-100 px-1.5 py-0.5 text-[10px] text-green-700">
        充足
      </span>
    );
  }
  if (quantity >= 3) {
    return (
      <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700">
        偏低
      </span>
    );
  }
  return (
    <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] text-red-700">
      紧张
    </span>
  );
}
