"""Topology GeoJSON endpoint — serves demo pipeline network as a map layer."""

from fastapi import APIRouter

from app.topology import load_demo_topology

router = APIRouter()


@router.get("/topology/geojson")
async def get_topology_geojson():
    """Return the demo pipeline topology as a GeoJSON FeatureCollection.

    Pipelines → LineString features, Valves → Point features.
    Frontend Leaflet map consumes this directly via ``L.geoJSON()``.
    """
    topo = load_demo_topology()

    features: list[dict] = []

    # ── Pipelines as LineStrings ──
    for pid, pipe in topo._pipelines.items():  # noqa: SLF001
        node_a = topo.get_node(pipe.node_a)
        node_b = topo.get_node(pipe.node_b)
        if not node_a or not node_b:
            continue
        if node_a.lat is None or node_a.lng is None:
            continue
        if node_b.lat is None or node_b.lng is None:
            continue

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [node_a.lng, node_a.lat],
                    [node_b.lng, node_b.lat],
                ],
            },
            "properties": {
                "id": pid,
                "type": "pipeline",
                "pressure_class": pipe.pressure_class,
                "material": pipe.material,
                "diameter": pipe.diameter,
                "length_m": pipe.length_m,
                "downstream_users": pipe.downstream_users,
            },
        })

    # ── Valves as Points ──
    for node_id, node in topo._nodes.items():  # noqa: SLF001
        if node.lat is None or node.lng is None:
            continue
        from app.topology.schema import Valve
        if isinstance(node, Valve):
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [node.lng, node.lat],
                },
                "properties": {
                    "id": node.id,
                    "type": "valve",
                    "label": node.label or node.id,
                    "status": node.status.value,
                    "remote_controllable": node.remote_controllable,
                    "manual_access": node.manual_access_desc,
                },
            })

    return {
        "type": "FeatureCollection",
        "features": features,
    }
