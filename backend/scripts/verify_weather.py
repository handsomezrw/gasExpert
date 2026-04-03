"""Verify QWeather via get_weather_info. Run from repo: backend\\scripts\\verify_weather.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tools.weather import get_weather_info


async def main() -> None:
    from app.config import get_settings

    s = get_settings()
    h = (s.weather_api_host or "").strip()
    print("weather_api_host:", h if h else "(empty — set WEATHER_API_HOST in .env)")
    print("weather_api_key set:", bool((s.weather_api_key or "").strip()))

    r = await get_weather_info.ainvoke({"location": "成都市武侯区"})
    src = r.get("source", "")
    ok = "和风天气" in str(src) and "模拟" not in str(src)
    print("source:", src)
    print("location:", r.get("location"))
    print("weather:", r.get("weather"), "| temp:", r.get("temperature"))
    print("result:", "OK (real API)" if ok else "FALLBACK (mock or API error)")


if __name__ == "__main__":
    asyncio.run(main())
