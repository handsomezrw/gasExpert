"""Weather information tool — QWeather API with mock fallback."""

import random

import httpx
import structlog
from langchain_core.tools import tool

from app.config import get_settings

logger = structlog.get_logger()

_WIND_DIRECTIONS = ["北风", "东北风", "东风", "东南风", "南风", "西南风", "西风", "西北风"]

_GAS_WEATHER_ADVICE = {
    "high_wind": "风速较大（≥6级），泄漏燃气扩散快，疏散范围应沿下风向扩大 50%，禁止明火作业。",
    "rain": "降雨天气，注意防滑和电气设备防水，PE 管熔接需搭建遮雨棚。",
    "low_temp": "低温天气（≤0℃），管道材料脆性增加，操作时避免剧烈冲击；注意人员防寒。",
    "high_temp": "高温天气（≥35℃），燃气挥发加速，检测仪报警阈值可适当下调；注意人员防暑。",
    "normal": "气象条件适中，按常规抢险流程操作即可。",
}


def _generate_advice(weather: dict) -> str:
    """Generate gas-emergency-specific advice based on weather conditions."""
    advices: list[str] = []
    wind_speed = weather.get("wind_speed", 0)
    temp = weather.get("temperature", 20)
    desc = weather.get("weather", "")

    if wind_speed >= 39:  # ≥6 级 (km/h)
        advices.append(_GAS_WEATHER_ADVICE["high_wind"])
    if any(k in desc for k in ("雨", "雷", "暴")):
        advices.append(_GAS_WEATHER_ADVICE["rain"])
    if temp <= 0:
        advices.append(_GAS_WEATHER_ADVICE["low_temp"])
    if temp >= 35:
        advices.append(_GAS_WEATHER_ADVICE["high_temp"])
    if not advices:
        advices.append(_GAS_WEATHER_ADVICE["normal"])
    return " ".join(advices)


async def _fetch_qweather(location: str) -> dict | None:
    """Call QWeather (和风天气) API to get real-time weather."""
    settings = get_settings()
    api_key = (settings.weather_api_key or "").strip()
    host = (settings.weather_api_host or "").strip().rstrip("/")
    if not api_key or not host:
        return None

    headers = {"X-QW-Api-Key": api_key}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            geo_resp = await client.get(
                f"{host}/geo/v2/city/lookup",
                params={"location": location, "number": 1},
                headers=headers,
            )
            geo_data = geo_resp.json()
            if geo_data.get("code") != "200" or not geo_data.get("location"):
                logger.warning("qweather_geo_failed", location=location, code=geo_data.get("code"))
                return None

            loc_id = geo_data["location"][0]["id"]
            loc_name = geo_data["location"][0]["name"]

            weather_resp = await client.get(
                f"{host}/v7/weather/now",
                params={"location": loc_id},
                headers=headers,
            )
            w = weather_resp.json()
            if w.get("code") != "200":
                logger.warning("qweather_weather_failed", code=w.get("code"))
                return None

            now = w["now"]
            return {
                "location": loc_name,
                "weather": now.get("text", ""),
                "temperature": float(now.get("temp", 0)),
                "feels_like": float(now.get("feelsLike", 0)),
                "humidity": int(now.get("humidity", 0)),
                "wind_direction": now.get("windDir", ""),
                "wind_speed": float(now.get("windSpeed", 0)),
                "wind_scale": now.get("windScale", ""),
                "pressure_hpa": float(now.get("pressure", 0)),
                "visibility_km": float(now.get("vis", 0)),
                "source": "和风天气实时数据",
            }
    except Exception as exc:
        logger.error("qweather_request_error", error=str(exc))
        return None


def _mock_weather(location: str) -> dict:
    """Return realistic mock weather data when no API key is configured."""
    return {
        "location": location,
        "weather": random.choice(["晴", "多云", "阴", "小雨"]),
        "temperature": round(random.uniform(5, 35), 1),
        "feels_like": round(random.uniform(3, 37), 1),
        "humidity": random.randint(30, 90),
        "wind_direction": random.choice(_WIND_DIRECTIONS),
        "wind_speed": round(random.uniform(2, 30), 1),
        "wind_scale": str(random.randint(1, 5)),
        "pressure_hpa": round(random.uniform(990, 1030), 1),
        "visibility_km": round(random.uniform(5, 30), 1),
        "source": "模拟数据（未配置 WEATHER_API_HOST 或 WEATHER_API_KEY）",
    }


@tool
async def get_weather_info(location: str) -> dict:
    """获取指定位置的实时气象信息，包含风向、风速、温度、湿度及燃气抢险相关建议。

    Args:
        location: 地理位置描述，如 "成都市武侯区"
    """
    weather = await _fetch_qweather(location)
    if weather is None:
        weather = _mock_weather(location)

    weather["gas_emergency_advice"] = _generate_advice(weather)
    return weather
