import { MapContainer, TileLayer, Marker, Popup, Polyline } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const COLOR = {
  off_duty: "#6b7280",
  sleeper_berth: "#7c3aed",
  driving: "#2563eb",
  on_duty_not_driving: "#d97706",
};

const icon = (status) =>
  L.divIcon({
    className: "stop-marker",
    html: `<div class="stop-marker-dot" style="background:${COLOR[status] ?? "#666"}">
             <span class="stop-marker-pulse"></span></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });

export default function RouteMap({ geometry, stops }) {
  const latlngs = geometry.map(([lon, lat]) => [lat, lon]);
  const center = latlngs[Math.floor(latlngs.length / 2)];

  return (
    <MapContainer center={center} zoom={5} scrollWheelZoom className="map">
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <Polyline positions={latlngs} pathOptions={{ color: "#2563eb", weight: 4, opacity: 0.85 }} />

      {stops.map((s, i) =>
        s.lat && s.lon ? (
          <Marker key={i} position={[s.lat, s.lon]} icon={icon(s.status)}>
            <Popup>
              <strong>{s.label}</strong>
              <br />
              <span className="muted">{s.kind}</span>
              <br />
              {s.time} · {s.duration_min} min
            </Popup>
          </Marker>
        ) : null
      )}
    </MapContainer>
  );
}