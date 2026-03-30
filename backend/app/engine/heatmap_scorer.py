"""
Heatmap scorer: evaluates route popularity using Strava heatmap tiles.

Falls back to neutral score (0.5) if tiles are unavailable.
"""

import logging
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

HEATMAP_URL = (
    "https://heatmap-external-a.strava.com/tiles-auth/cycling/bluered/{z}/{x}/{y}.png"
)


class HeatmapScorer:
    def __init__(self, access_token: str | None = None):
        self.access_token = access_token or settings.strava_access_token
        self.enabled = bool(self.access_token) and settings.use_strava_heatmap
        self.cache_dir = settings.cache_path / "heatmap"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def score_edges(
        self,
        edge_coords: list[tuple[float, float]],
    ) -> list[float]:
        """Score a list of edge midpoints by heatmap intensity.

        Args:
            edge_coords: list of (lat, lon) midpoints for each edge

        Returns:
            List of scores in [0, 1] for each edge.
        """
        if not self.enabled:
            return [0.5] * len(edge_coords)

        try:
            scores = []
            for lat, lon in edge_coords:
                score = await self._score_point(lat, lon)
                scores.append(score)
            return scores
        except Exception as e:
            logger.warning("Heatmap scoring failed: %s. Using neutral scores.", e)
            return [0.5] * len(edge_coords)

    async def _score_point(self, lat: float, lon: float, zoom: int = 14) -> float:
        """Score a single point by fetching the heatmap tile."""
        import math

        # Convert lat/lon to tile coordinates
        n = 2**zoom
        x = int((lon + 180) / 360 * n)
        y = int(
            (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi)
            / 2
            * n
        )

        # Check cache
        cache_file = self.cache_dir / f"{zoom}_{x}_{y}.png"
        if cache_file.exists():
            return self._read_tile_intensity(cache_file, lat, lon, x, y, zoom)

        # Fetch tile
        url = HEATMAP_URL.format(z=zoom, x=x, y=y)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {self.access_token}"},
                    timeout=10.0,
                )
                if resp.status_code == 403:
                    logger.warning("Strava heatmap auth failed (403)")
                    self.enabled = False
                    return 0.5
                resp.raise_for_status()

                cache_file.write_bytes(resp.content)
                return self._read_tile_intensity(cache_file, lat, lon, x, y, zoom)
        except Exception as e:
            logger.warning("Failed to fetch heatmap tile: %s", e)
            return 0.5

    def _read_tile_intensity(
        self,
        tile_path: Path,
        lat: float,
        lon: float,
        tile_x: int,
        tile_y: int,
        zoom: int,
    ) -> float:
        """Read pixel intensity from a cached tile PNG."""
        try:
            from PIL import Image

            img = Image.open(tile_path)
            width, height = img.size

            import math

            n = 2**zoom
            # Pixel position within tile
            px_x = int(((lon + 180) / 360 * n - tile_x) * width)
            lat_rad = math.radians(lat)
            px_y = int(
                (
                    (1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi)
                    / 2
                    * n
                    - tile_y
                )
                * height
            )

            px_x = max(0, min(px_x, width - 1))
            px_y = max(0, min(px_y, height - 1))

            pixel = img.getpixel((px_x, px_y))
            # Red channel = intensity in bluered colormap
            red = pixel[0] if isinstance(pixel, tuple) else pixel
            return red / 255.0

        except ImportError:
            logger.warning("Pillow not installed, heatmap scoring disabled")
            self.enabled = False
            return 0.5
        except Exception as e:
            logger.warning("Failed to read tile intensity: %s", e)
            return 0.5
