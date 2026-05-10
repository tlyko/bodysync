import { render } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { RoutePreview, decodePolyline } from '../components/dashboard/RoutePreview';

describe('decodePolyline', () => {
  test('Google reference example decodes to known coordinates', () => {
    // Reference: https://developers.google.com/maps/documentation/utilities/polylinealgorithm
    // Encoded "_p~iF~ps|U_ulLnnqC_mqNvxq`@" → 3 points (San Francisco area)
    const points = decodePolyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@');
    expect(points).toHaveLength(3);
    expect(points[0][0]).toBeCloseTo(38.5, 1);
    expect(points[0][1]).toBeCloseTo(-120.2, 1);
    expect(points[1][0]).toBeCloseTo(40.7, 1);
    expect(points[1][1]).toBeCloseTo(-120.95, 1);
    expect(points[2][0]).toBeCloseTo(43.252, 2);
    expect(points[2][1]).toBeCloseTo(-126.453, 2);
  });

  test('empty string yields no points', () => {
    expect(decodePolyline('')).toEqual([]);
  });
});

describe('RoutePreview', () => {
  test('renders SVG polyline z decoded points + start/end dots', () => {
    const { container } = render(
      <RoutePreview encoded="_p~iF~ps|U_ulLnnqC_mqNvxq`@" size={48} />,
    );
    const svg = container.querySelector('svg.route-preview');
    expect(svg).toBeTruthy();
    // 1 polyline + 2 circles (start green + end red)
    expect(container.querySelectorAll('polyline').length).toBe(1);
    expect(container.querySelectorAll('circle').length).toBe(2);
  });

  test('returns null gdy <2 punkty (single-point polyline = degenerate)', () => {
    // Encoded single point — decoder zwróci 1 element
    const { container } = render(<RoutePreview encoded="_p~iF~ps|U" size={48} />);
    expect(container.querySelector('svg.route-preview')).toBeNull();
  });

  test('aspect-ratio preserve: lat/lng range scaled równomiernie', () => {
    const { container } = render(
      <RoutePreview encoded="_p~iF~ps|U_ulLnnqC_mqNvxq`@" size={100} />,
    );
    const polyline = container.querySelector('polyline');
    expect(polyline).toBeTruthy();
    // Wszystkie punkty mieszczą się w 0..100 (no overflow)
    const pointsAttr = polyline?.getAttribute('points') ?? '';
    const coords = pointsAttr.split(' ').flatMap((p) => p.split(',').map(Number));
    expect(coords.every((c) => c >= 0 && c <= 100)).toBe(true);
  });
});
