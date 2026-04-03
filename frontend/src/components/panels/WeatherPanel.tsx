import { Cloud, Thermometer, Wind, Droplets, Eye } from "lucide-react";

interface Props {
  data: Record<string, unknown>;
}

export function WeatherPanel({ data }: Props) {
  const location = (data.location as string) ?? "";
  const weather = (data.weather as string) ?? (data.text as string) ?? "晴";
  const temp = data.temperature ?? data.temp;
  const humidity = data.humidity;
  const windSpeed = data.wind_speed ?? data.windSpeed;
  const windDir = data.wind_direction ?? data.wind_dir ?? data.windDir ?? "";
  const visibility = data.visibility_km ?? data.visibility;
  const advice = (data.gas_emergency_advice as string) ?? (data.advice as string) ?? "";

  return (
    <div className="rounded-xl border border-sky-200 bg-gradient-to-br from-sky-50 to-blue-50 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Cloud className="h-5 w-5 text-sky-600" />
        <h3 className="text-sm font-semibold text-sky-700">现场天气信息</h3>
        {location && (
          <span className="ml-auto text-xs text-sky-600/70">{location}</span>
        )}
      </div>

      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {temp != null && (
          <WeatherMetric
            icon={<Thermometer className="h-4 w-4 text-orange-500" />}
            label="温度"
            value={`${temp}°C`}
          />
        )}
        {humidity != null && (
          <WeatherMetric
            icon={<Droplets className="h-4 w-4 text-blue-500" />}
            label="湿度"
            value={`${humidity}%`}
          />
        )}
        {windSpeed != null && (
          <WeatherMetric
            icon={<Wind className="h-4 w-4 text-teal-500" />}
            label={`风速${windDir ? `(${windDir})` : ""}`}
            value={`${windSpeed} km/h`}
          />
        )}
        {visibility != null && (
          <WeatherMetric
            icon={<Eye className="h-4 w-4 text-purple-500" />}
            label="能见度"
            value={`${visibility} km`}
          />
        )}
      </div>

      <div className="flex items-center gap-2 rounded-lg bg-white/50 px-3 py-2 text-xs">
        <span className="font-medium text-sky-700">天气状况:</span>
        <span className="text-foreground">{weather}</span>
      </div>

      {advice && (
        <div className="mt-2 rounded-lg bg-amber-50/80 border border-amber-200/50 px-3 py-2 text-xs text-amber-800">
          <span className="font-medium">应急建议: </span>
          {advice}
        </div>
      )}
    </div>
  );
}

function WeatherMetric({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex flex-col items-center rounded-lg bg-white/60 p-2.5">
      {icon}
      <span className="mt-1 text-sm font-semibold text-foreground">{value}</span>
      <span className="text-[10px] text-muted-foreground">{label}</span>
    </div>
  );
}
