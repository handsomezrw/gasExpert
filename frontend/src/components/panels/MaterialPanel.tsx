interface InventoryItem {
  name: string;
  quantity: number;
}

interface Station {
  station_name: string;
  distance_km: number;
  items: InventoryItem[];
}

interface Props {
  stations: Station[];
}

export function MaterialPanel({ stations }: Props) {
  if (stations.length === 0) return null;

  return (
    <div className="rounded-md border bg-card p-4 space-y-3">
      <h3 className="text-sm font-semibold">物资库存查询结果</h3>
      {stations.map((s) => (
        <div key={s.station_name} className="space-y-1">
          <p className="text-sm font-medium">
            {s.station_name}
            <span className="ml-2 text-xs text-muted-foreground">
              {s.distance_km} km
            </span>
          </p>
          <div className="grid grid-cols-3 gap-1 text-xs">
            {s.items.map((item) => (
              <span
                key={item.name}
                className="rounded bg-muted px-2 py-1 text-center"
              >
                {item.name}: {item.quantity}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
