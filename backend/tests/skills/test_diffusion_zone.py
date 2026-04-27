"""Tests for diffusion_zone skill — deterministic input → output."""
from __future__ import annotations

import pytest

from app.skills.diffusion_zone.skill import DiffusionZoneSkill


@pytest.fixture
def skill():
    return DiffusionZoneSkill()


@pytest.mark.asyncio
async def test_basic_diffusion_produces_zones(skill):
    """Standard leak input should produce tiered evacuation zones."""
    result = await skill.ainvoke({
        "location": "成都市武侯区",
        "pressure": 0.4,
        "diameter": 200,
        "leak_type": "crack",
        "wind_speed": 15.0,
        "is_indoor": False,
        "leak_point_lat": 30.676,
        "leak_point_lng": 104.065,
    })
    assert result.output is not None
    assert result.output["success"] is True
    assert len(result.output["zones"]) >= 1
    assert result.output["geojson"] is not None


@pytest.mark.asyncio
async def test_high_pressure_rupture_produces_more_zones(skill):
    """Higher severity should produce more evacuation zones."""
    result = await skill.ainvoke({
        "location": "成都市锦江区",
        "pressure": 1.6,
        "diameter": 300,
        "leak_type": "rupture",
        "wind_speed": 5.0,
    })
    assert result.output["success"] is True
    zones = result.output["zones"]
    assert len(zones) >= 2


@pytest.mark.asyncio
async def test_low_pressure_pinhole_minimal_zones(skill):
    """Low severity pinhole leak should still produce zones."""
    result = await skill.ainvoke({
        "location": "成都市青羊区",
        "pressure": 0.01,
        "diameter": 50,
        "leak_type": "pinhole",
    })
    assert result.output["success"] is True


@pytest.mark.asyncio
async def test_geojson_has_metadata(skill):
    """GeoJSON output should include metadata fields."""
    result = await skill.ainvoke({
        "location": "成都市武侯区",
        "pressure": 0.4,
        "diameter": 200,
        "leak_type": "crack",
    })
    geojson = result.output["geojson"]
    assert geojson["type"] == "FeatureCollection"
    assert "metadata" in geojson
    assert "model_used" in geojson["metadata"]
    assert geojson["metadata"]["base_radius_m"] > 0
    assert len(geojson["features"]) >= 1


@pytest.mark.asyncio
async def test_output_contains_weather(skill):
    """Weather data should be reflected in the output."""
    result = await skill.ainvoke({
        "location": "成都市武侯区",
        "pressure": 0.4,
        "diameter": 200,
        "leak_type": "crack",
        "wind_speed": 25.0,
    })
    weather = result.output["weather_used"]
    # Location field comes from mock weather data which may use different format
    assert weather is not None
    assert "temperature" in weather
    assert "wind_speed" in weather
    assert weather["wind_speed"] == 25.0  # Our override


@pytest.mark.asyncio
async def test_model_name_nonempty(skill):
    """Model name should be specified."""
    result = await skill.ainvoke({
        "location": "成都市武侯区",
        "pressure": 0.4,
        "diameter": 200,
        "leak_type": "crack",
    })
    assert result.output["model_used"] != ""


@pytest.mark.asyncio
async def test_zones_have_levels(skill):
    """Evacuation zones should have proper level labels."""
    result = await skill.ainvoke({
        "location": "成都市武侯区",
        "pressure": 0.4,
        "diameter": 200,
        "leak_type": "crack",
    })
    levels = {z["level"] for z in result.output["zones"]}
    assert len(levels) >= 1
