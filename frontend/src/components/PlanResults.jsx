import RouteMap from "./RouteMap";
import HoursCluster from "./HoursCluster";
import StopTimeline from "./StopTimeline";
import LogSheet from "./LogSheet";

/** full plan renderer: route summary, map, instrument gauges, stop
 * timeline and the daily log sheets. shared by the live planner, saved
 * trips, and the public explorer so every view renders identically. */
export default function PlanResults({ result, pickup, dropoff }) {
  const vehicleNo =
    result.vehicle?.unit_no ??
    result.trip?.vehicle?.unit_no ??
    result.driver?.vehicle_unit ??
    "";

  return (
    <div className="results">
      <div className="route-summary">
        <span>{pickup}</span>
        <span className="route-arrow">→</span>
        <span>{dropoff}</span>
        <span className="route-sep">·</span>
        <span className="num route-miles">{result.route?.distance_miles ?? result.distance_miles}</span>
        <span className="route-unit">mi</span>
        {(result.route?.highways ?? result.highways ?? []).length > 0 && (
          <>
            <span className="route-sep">·</span>
            <span className="roadshield">
              {(result.route?.highways ?? result.highways ?? []).join(" / ")}
            </span>
          </>
        )}
      </div>

      <RouteMap
        geometry={result.route?.geometry ?? result.route_geometry}
        stops={result.stops}
      />

      <HoursCluster usage={result.usage} />

      <StopTimeline stops={result.stops} />

      <h2 className="section-head">Daily logs</h2>
      <div className="logs">
        {(result.daily_logs || []).map((day, i) => (
          <div
            key={day.day_number ?? i}
            className="sheet-stagger"
            style={{ animationDelay: `${i * 150}ms` }}
          >
            <LogSheet
              day={day}
              index={i}
              cycleUsed={result.usage?.cycle_hours ?? result.cycle_used}
              vehicleNo={vehicleNo}
            />
          </div>
        ))}
      </div>
    </div>
  );
}