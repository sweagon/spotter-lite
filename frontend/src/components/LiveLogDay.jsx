import LogSheet from "./LogSheet";

/** the driver's live RODS for today — drawn from real duty events via the
 * same LogSheet geometry as the planned sheets, so the checksum still sums
 * to 24.00. planning-grade, not an engine-linked ELD record. */
export default function LiveLogDay({ day, cycleUsed, drivingHours }) {
  if (!day) return null;
  return (
    <div className="live-log">
      <div className="live-log-head">
        <div>
          <p className="live-log-title">Today's record of duty status</p>
          <p className="live-log-sub">
            live from your duty signals · self-declared, planning-grade · totals always balance to 24.00
          </p>
        </div>
        <div className="live-log-stat num">
          <span className="live-log-stat-num">{drivingHours ?? 0}</span>
          <span className="live-log-stat-label">driving hrs today</span>
        </div>
      </div>
      <LogSheet day={day} index={0} cycleUsed={cycleUsed} />
    </div>
  );
}