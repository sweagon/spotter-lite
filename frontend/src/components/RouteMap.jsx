import { useEffect, useRef } from "react";
import { MapContainer, TileLayer, Marker, Popup, Polyline } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

/**
 * route map. teal polyline that draws itself on submit (the one motion
 * moment), marker dots keyed off stop_type — the same mapping the stop
 * timeline uses — and a petrol popover per stop.
 */
const DOT_COLOR = {
  pickup: "#bcddde", // mint — pickup / dropoff
  dropoff: "#bcddde",
  fuel: "#f84960", // coral — fuel stops
  break: "#008080", // teal — breaks / rests
  rest: "#008080",
  restart: "#008080",
  on_duty: "#008080",
};

const iconFor = (stop) =>
  L.divIcon({
    className: "map-dot",
    html: `<div class="map-dot-inner" style="background:${DOT_COLOR[stop.stop_type] ?? "#9fb4b8"}"></div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });

export default function RouteMap({ geometry, stops }) {
  const pathRef = useRef(null);
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const latlngs = (geometry ?? []).map(([lon, lat]) => [lat, lon]);
  if (latlngs.length < 2) {
    return <div className="map"><div className="map-empty-note">Route preview unavailable.</div></div>;
  }
  const center = latlngs[Math.floor(latlngs.length / 2)];
  // draw the polyline in on mount: full dash, then transition to 0 offset.
  const dash = reduced ? undefined : [latlngs.length * 1000];

  return (
    <MapContainer center={center} zoom={5} scrollWheelZoom className="map">
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <Polyline
        positions={latlngs}
        pathOptions={{
          color: "#008080",
          weight: 4,
          opacity: 0.9,
          dashArray: dash,
          dashOffset: reduced ? undefined : "100%",
        }}
        ref={pathRef}
      />
      {!reduced && <DrawDriver pathRef={pathRef} />}

      {stops.map((s, i) =>
        s.lat && s.lon ? (
          <Marker key={i} position={[s.lat, s.lon]} icon={iconFor(s)}>
            <Popup className="stop-popup">
              <strong>{s.label}</strong>
              <span className="num">{s.day} · {s.time} · mi {s.mile}</span>
            </Popup>
          </Marker>
        ) : null
      )}
    </MapContainer>
  );
}

/** flips the dashoffset after mount (next frame) so CSS animates the draw. */
function DrawDriver({ pathRef }) {
  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      pathRef.current?.setStyle({ dashOffset: "0%" });
    });
    return () => cancelAnimationFrame(raf);
  }, [pathRef]);
  return null;
}