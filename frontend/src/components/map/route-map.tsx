"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";

// Leaflet must be dynamically imported (no SSR)
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
const Popup = dynamic(
  () => import("react-leaflet").then((m) => m.Popup),
  { ssr: false }
);
const Marker = dynamic(
  () => import("react-leaflet").then((m) => m.Marker),
  { ssr: false }
);

interface RouteMapProps {
  geojson: GeoJSON.FeatureCollection | null;
  center?: [number, number];
  zoom?: number;
  height?: string;
}

export function RouteMap({
  geojson,
  center = [48.1173, -1.6778],
  zoom = 12,
  height = "500px",
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

  return (
    <div style={{ height }} className="rounded-lg overflow-hidden">
      <MapContainer
        center={center}
        zoom={zoom}
        style={{ height: "100%", width: "100%" }}
        scrollWheelZoom
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org">OSM</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {geojson && (
          <GeoJSON
            key={JSON.stringify(geojson).slice(0, 100)}
            data={geojson}
            style={(feature) => {
              if (feature?.geometry.type === "Point") return {};
              const props = feature?.properties || {};
              return {
                color: props.color || "#6b7280",
                weight: props.block_type === "interval" ? 5 : 3,
                opacity: 0.9,
              };
            }}
            onEachFeature={(feature, layer) => {
              const props = feature.properties;
              if (feature.geometry.type === "LineString") {
                const label =
                  props.block_type === "interval"
                    ? `Intervalle: ${props.power_target}W | ${props.distance_km} km`
                    : `${props.block_type}: ${props.distance_km} km | ${props.duration_min} min`;
                layer.bindPopup(label);
              } else if (props.marker_type) {
                layer.bindPopup(
                  `${props.label}${
                    props.power_target ? ` | ${props.power_target}W` : ""
                  }${
                    props.avg_grade ? ` | ${props.avg_grade}%` : ""
                  }`
                );
              }
            }}
            pointToLayer={(feature, latlng) => {
              // Use dynamic import for L
              const L = require("leaflet");
              const props = feature.properties;
              const isClimb = props.marker_type === "climb_start";
              const isStart = props.marker_type === "interval_start";

              return L.circleMarker(latlng, {
                radius: isClimb ? 8 : 6,
                fillColor: isClimb ? "#f59e0b" : isStart ? "#ef4444" : "#22c55e",
                color: "#fff",
                weight: 2,
                fillOpacity: 0.9,
              });
            }}
          />
        )}
      </MapContainer>
    </div>
  );
}
