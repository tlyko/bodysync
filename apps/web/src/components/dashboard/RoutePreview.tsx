// Sprint 10 A9 — thumbnail mapy trasy z Strava `summary_polyline`.
//
// Strava encoded polyline = Google Encoded Polyline Algorithm Format
// (https://developers.google.com/maps/documentation/utilities/polylinealgorithm).
// Każda para chars = lat/lng delta z poprzedniego punktu, encoded base64.
//
// Decision: NO leaflet/mapbox (~50KB+ JS + tile bandwidth + network call).
// Inline SVG polyline z decoded points pokazuje shape trasy bez geo
// kontekstu. Owner widzi czy to pętla / point-to-point / chaotic interval.
// Akceptowalny trade-off na thumbnail (50×50px ActivityRow).

type RoutePreviewProps = {
  encoded: string;
  size?: number;
};

/**
 * Decode Google Encoded Polyline format.
 *
 * Format: każda wartość lat/lng delta jest zakodowana jako serie 5-bit
 * chunks z high-bit jako continuation flag. Zwraca array [lat, lng] par.
 *
 * Reference: https://developers.google.com/maps/documentation/utilities/polylinealgorithm
 */
export function decodePolyline(encoded: string): Array<[number, number]> {
  const points: Array<[number, number]> = [];
  let index = 0;
  let lat = 0;
  let lng = 0;
  while (index < encoded.length) {
    let result = 1;
    let shift = 0;
    let byte: number;
    do {
      byte = encoded.charCodeAt(index++) - 63 - 1;
      result += byte << shift;
      shift += 5;
    } while (byte >= 0x1f);
    lat += result & 1 ? ~(result >> 1) : result >> 1;

    result = 1;
    shift = 0;
    do {
      byte = encoded.charCodeAt(index++) - 63 - 1;
      result += byte << shift;
      shift += 5;
    } while (byte >= 0x1f);
    lng += result & 1 ? ~(result >> 1) : result >> 1;

    points.push([lat * 1e-5, lng * 1e-5]);
  }
  return points;
}

export function RoutePreview({ encoded, size = 48 }: RoutePreviewProps) {
  const points = decodePolyline(encoded);
  if (points.length < 2) return null;

  const lats = points.map((p) => p[0]);
  const lngs = points.map((p) => p[1]);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);

  // Scale to size×size box, preserve aspect ratio (no skew). Pad 4px na
  // każdy bok żeby polyline nie dotykała krawędzi.
  const PAD = 4;
  const innerSize = size - 2 * PAD;
  const latRange = maxLat - minLat || 1;
  const lngRange = maxLng - minLng || 1;
  const scale = Math.min(innerSize / latRange, innerSize / lngRange);
  // Center horizontally i vertically wewnątrz box.
  const offsetX = (size - lngRange * scale) / 2;
  const offsetY = (size - latRange * scale) / 2;

  // Note: Y oś SVG idzie w dół, lat rośnie do góry — flip na rendering.
  const polylineStr = points
    .map(([lat, lng]) => {
      const x = offsetX + (lng - minLng) * scale;
      const y = offsetY + (maxLat - lat) * scale;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <svg
      className="route-preview"
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`Mapa trasy (${points.length} punktów)`}
    >
      <polyline
        points={polylineStr}
        fill="none"
        stroke="#22d3ee"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.9"
      />
      {/* Start dot — green */}
      <circle
        cx={offsetX + (points[0][1] - minLng) * scale}
        cy={offsetY + (maxLat - points[0][0]) * scale}
        r="2"
        fill="#10b981"
      />
      {/* End dot — red */}
      <circle
        cx={offsetX + (points[points.length - 1][1] - minLng) * scale}
        cy={offsetY + (maxLat - points[points.length - 1][0]) * scale}
        r="2"
        fill="#ef4444"
      />
    </svg>
  );
}
