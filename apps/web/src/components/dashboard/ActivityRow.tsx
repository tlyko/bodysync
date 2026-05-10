import type { Activity } from '../../types';
import {
  formatDistance,
  formatDuration,
  formatPace,
  formatRelativeDate,
  sportIcon,
  sportLabel,
} from './activities';
import { RoutePreview } from './RoutePreview';

type Props = { activity: Activity };

export function ActivityRow({ activity }: Props) {
  const isRun =
    activity.sport_type.toLowerCase().includes('run') || activity.sport_type === 'TrailRun';
  const pace = isRun ? formatPace(activity.distance_m, activity.moving_time_s) : null;
  const dateLabel = formatRelativeDate(activity.start_date_local);

  return (
    <div className="activity-row">
      {/* Sprint 10 A9 — gdy mamy polyline, thumbnail mapy zastępuje sport
          emoji icon. Sport bez GPS / pre-A9 activity → fallback emoji. */}
      {activity.summary_polyline ? (
        <span className="activity-row-thumb">
          <RoutePreview encoded={activity.summary_polyline} size={48} />
        </span>
      ) : (
        <span className="activity-row-icon" aria-hidden>
          {sportIcon(activity.sport_type)}
        </span>
      )}
      <div className="activity-row-main">
        <div className="activity-row-name">{activity.name}</div>
        <div className="activity-row-meta">
          {sportLabel(activity.sport_type)} · {dateLabel}
        </div>
      </div>
      <div className="activity-row-stats">
        <span className="activity-row-distance">{formatDistance(activity.distance_m)}</span>
        <span className="activity-row-duration">{formatDuration(activity.moving_time_s)}</span>
        {pace && <span className="activity-row-pace">{pace}</span>}
        {activity.average_heartrate != null && (
          <span className="activity-row-hr">{Math.round(activity.average_heartrate)} bpm</span>
        )}
        {activity.calories != null && (
          <span className="activity-row-kcal">{Math.round(activity.calories)} kcal</span>
        )}
      </div>
    </div>
  );
}
