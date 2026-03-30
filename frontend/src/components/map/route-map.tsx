"use client";

import { useEffect, useState, useRef } from "react";
import dynamic from "next/dynamic";

const MapContainer = dynamic(
  () => import("react-leaflet").then((m) => m.MapContainer),
  { ssr: false }
);
const TileLayer = dynamic(
  () => import("react-leaflet").then((m) => m.TileLayer),
  { ssr: false }
);
const GeoJSON = dynamic(
  () => import("react-leaflet").then((m) => m.GeoJSON),
  { ssr: false }
);
const CircleMarker = dynamic(
  () => import("react-leaflet").then((m) => m.CircleMarker),
  { ssr: false }
);

interface RouteMapProps {
  geojson: GeoJSON.FeatureCollection | null;
  center?: [number, number];
  zoom?: number;
  height?: string;
  hoverPoint?: { lat: number; lon: number } | null;
}

export function RouteMap({
  geojson,
  center = [48.1173, -1.6778],
  zoom = 13,
  height = "500px",
  hoverPoint,
}: RouteMapProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <div
        style={{ height }}
        className="bg-gray-800 rounded-lg flex items-center justify-center"
      >
        <p className="text-gray-500">Chargement de la carte...</p>
      </div>
    );
  }

  const computedCenter = geojson ? _computeCenter(geojson) : center;

  return (
    <div style={{ height }} className="rounded-lg overflow-hidden border border-gray-700">
      <MapContainer
        center={computedCenter}
        zoom={zoom}
        style={{ height: "100%", width: "100%" }}
        scrollWheelZoom
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org">OSM</a> &copy; <a href="https://carto.com">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />

        {geojson && (
          <GeoJSON
            key={JSON.stringify(geojson).slice(0, 100)}
            data={geojson}
            style={(feature) => {
              if (feature?.geometry.type === "Point") return {};
              const props = feature?.properties || {};
              const isInterval = props.block_type === "interval";
              return {
                color: props.color || "#6b7280",
                weight: isInterval ? 6 : 4,
                opacity: 1,
                lineCap: "round",
                lineJoin: "round",
              };
            }}
            onEachFeature={(feature, layer) => {
              const props = feature.properties;
              if (feature.geometry.type === "LineString") {
                const label =
                  props.block_type === "interval"
                    ? `<b>Intervalle</b><br/>${props.power_target}W | ${props.distance_km} km | ${props.duration_min} min`
                    : `<b>${_blockLabel(props.block_type)}</b><br/>${props.distance_km} km | ${props.duration_min} min | ${props.avg_speed_kmh} km/h`;
                layer.bindPopup(label);
              } else if (props.marker_type === "start") {
                layer.bindPopup(`<b>${props.label}</b>`);
              } else if (props.marker_type === "finish") {
                layer.bindPopup(`<b>${props.label}</b>`);
              }
            }}
            pointToLayer={(feature, latlng) => {
              const L = require("leaflet");
              const props = feature.properties;
              const isStart = props.marker_type === "start";

              return L.circleMarker(latlng, {
                radius: 10,
                fillColor: isStart ? "#22c55e" : "#3b82f6",
                color: "#ffffff",
                weight: 3,
                fillOpacity: 1,
              });
            }}
          />
        )}

        {/* Cursor that follows elevation profile hover */}
        {hoverPoint && (
          <CircleMarker
            center={[hoverPoint.lat, hoverPoint.lon]}
            radius={8}
            pathOptions={{
              fillColor: "#facc15",
              color: "#ffffff",
              weight: 3,
              fillOpacity: 1,
            }}
          />
        )}
      </MapContainer>
    </div>
  );
}

function _computeCenter(geojson: GeoJSON.FeatureCollection): [number, number] {
  const lines = geojson.features.filter(
    (f) => f.geometry.type === "LineString"
  );
  if (lines.length === 0) return [48.1173, -1.6778];

  let sumLat = 0, sumLon = 0, count = 0;
  for (const feat of lines) {
    const coords = (feat.geometry as GeoJSON.LineString).coordinates;
    for (const c of coords) {
      sumLon += c[0];
      sumLat += c[1];
      count++;
    }
  }
  return [sumLat / count, sumLon / count];
}

function _blockLabel(type: string): string {
  const labels: Record<string, string> = {
    warmup: "Echauffement",
    interval: "Intervalle",
    recovery: "Recuperation",
    cooldown: "Retour au calme",
  };
  return labels[type] || type;
}
