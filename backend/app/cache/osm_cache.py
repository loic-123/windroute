"""
OSM graph cache: serializes/deserializes OSMnx graphs to disk.

Cache key is based on center point + radius. Graphs are stored as
GraphML files for portability.
"""

import hashlib
import logging
from pathlib import Path

import networkx as nx

from app.config import settings

logger = logging.getLogger(__name__)


def _cache_key(lat: float, lon: float, radius_m: float) -> str:
    """Generate a cache key from location and radius."""
    # Round to avoid cache misses for tiny coordinate differences
    key_str = f"{lat:.3f}_{lon:.3f}_{radius_m:.0f}"
    return hashlib.md5(key_str.encode()).hexdigest()


def get_cache_path(lat: float, lon: float, radius_m: float) -> Path:
    cache_dir = settings.cache_path / "osm"
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(lat, lon, radius_m)
    return cache_dir / f"graph_{key}.graphml"


def load_cached_graph(
    lat: float, lon: float, radius_m: float
) -> nx.MultiDiGraph | None:
    """Load a cached OSMnx graph if available."""
    path = get_cache_path(lat, lon, radius_m)
    if path.exists():
        try:
            import osmnx as ox

            graph = ox.load_graphml(path)
            logger.info("Loaded cached graph from %s (%d nodes)", path.name, len(graph.nodes))
            return graph
        except Exception as e:
            logger.warning("Failed to load cached graph: %s", e)
            path.unlink(missing_ok=True)
    return None


def save_graph_to_cache(
    graph: nx.MultiDiGraph,
    lat: float,
    lon: float,
    radius_m: float,
) -> None:
    """Save an OSMnx graph to the cache."""
    path = get_cache_path(lat, lon, radius_m)
    try:
        import osmnx as ox

        ox.save_graphml(graph, path)
        logger.info(
            "Saved graph to cache: %s (%d nodes)", path.name, len(graph.nodes)
        )
    except Exception as e:
        logger.warning("Failed to cache graph: %s", e)


def load_or_fetch_graph(
    lat: float,
    lon: float,
    radius_m: float,
    network_type: str = "bike",
) -> nx.MultiDiGraph:
    """Load graph from cache or fetch from OSM.

    Args:
        lat: center latitude
        lon: center longitude
        radius_m: search radius in meters
        network_type: OSMnx network type (default: "bike")

    Returns:
        OSMnx MultiDiGraph
    """
    import osmnx as ox

    cached = load_cached_graph(lat, lon, radius_m)
    if cached is not None:
        return cached

    logger.info(
        "Fetching OSM graph: center=(%.4f, %.4f), radius=%.0fm",
        lat,
        lon,
        radius_m,
    )

    graph = ox.graph_from_point(
        (lat, lon),
        dist=radius_m,
        network_type=network_type,
        retain_all=False,
    )

    logger.info("Fetched graph: %d nodes, %d edges", len(graph.nodes), len(graph.edges))

    save_graph_to_cache(graph, lat, lon, radius_m)
    return graph


def enrich_elevations(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Add elevation data to graph nodes.

    Tries open-elevation API via httpx, then falls back to setting
    elevation=0 for all nodes (flat terrain approximation).
    """
    # Check how many nodes already have elevation
    nodes_with_ele = sum(
        1 for _, d in graph.nodes(data=True) if "elevation" in d
    )
    total = len(graph.nodes)

    if nodes_with_ele >= total * 0.9:
        logger.info("Graph already has elevation data (%d/%d nodes)", nodes_with_ele, total)
        return _add_edge_grades(graph)

    logger.info("Enriching %d nodes with elevation data...", total - nodes_with_ele)

    try:
        graph = _fetch_elevations_open(graph)
    except Exception as e:
        logger.warning(
            "Failed to fetch elevations: %s. Using flat terrain (elevation=0).", e
        )
        for node in graph.nodes:
            if "elevation" not in graph.nodes[node]:
                graph.nodes[node]["elevation"] = 0.0

    return _add_edge_grades(graph)


def _fetch_elevations_open(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Fetch elevations from open-elevation.com API in batches."""
    import httpx

    nodes_need = [
        (n, d["y"], d["x"])
        for n, d in graph.nodes(data=True)
        if "elevation" not in d
    ]

    batch_size = 200
    for i in range(0, len(nodes_need), batch_size):
        batch = nodes_need[i : i + batch_size]
        locations = [{"latitude": lat, "longitude": lon} for _, lat, lon in batch]

        try:
            resp = httpx.post(
                "https://api.open-elevation.com/api/v1/lookup",
                json={"locations": locations},
                timeout=30.0,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            for (node_id, _, _), result in zip(batch, results):
                graph.nodes[node_id]["elevation"] = result.get("elevation", 0.0)
        except Exception as e:
            logger.warning("Open-elevation batch %d failed: %s", i, e)
            for node_id, _, _ in batch:
                graph.nodes[node_id]["elevation"] = 0.0

    return graph


def _add_edge_grades(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Compute grade for each edge from node elevations."""
    for u, v, key, data in graph.edges(keys=True, data=True):
        ele_u = graph.nodes[u].get("elevation", 0)
        ele_v = graph.nodes[v].get("elevation", 0)
        length = data.get("length", 0)
        if length > 0:
            data["grade"] = (ele_v - ele_u) / length
            data["grade_abs"] = abs(data["grade"])
        else:
            data["grade"] = 0.0
            data["grade_abs"] = 0.0
    return graph
