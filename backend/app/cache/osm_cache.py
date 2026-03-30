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
    """Add elevation data to graph nodes using local SRTM data.

    Uses the srtm.py package which auto-downloads SRTM tiles to
    ~/.cache/srtm/ on first use. After that, lookups are instant.
    No API calls, no rate limiting, works offline.
    """
    import srtm

    nodes_with_ele = sum(
        1 for _, d in graph.nodes(data=True) if "elevation" in d
    )
    total = len(graph.nodes)

    if nodes_with_ele >= total * 0.9:
        logger.info("Graph already has elevation data (%d/%d nodes)", nodes_with_ele, total)
        return _add_edge_grades(graph)

    logger.info("Enriching %d nodes with SRTM elevation data...", total - nodes_with_ele)

    try:
        srtm_data = srtm.get_data()
        enriched = 0
        for node, data in graph.nodes(data=True):
            if "elevation" not in data:
                lat = data.get("y", 0)
                lon = data.get("x", 0)
                ele = srtm_data.get_elevation(lat, lon)
                data["elevation"] = ele if ele is not None else 0.0
                if ele is not None:
                    enriched += 1

        logger.info("SRTM elevation: %d/%d nodes enriched", enriched, total)

    except Exception as e:
        logger.warning("SRTM elevation failed: %s. Using flat terrain.", e)
        for node in graph.nodes:
            if "elevation" not in graph.nodes[node]:
                graph.nodes[node]["elevation"] = 0.0

    return _add_edge_grades(graph)


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
