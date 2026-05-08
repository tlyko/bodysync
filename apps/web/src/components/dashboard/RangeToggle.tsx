export type Range = '1d' | '7d' | '30d';

const OPTIONS: Array<{ value: Range; label: string }> = [
  { value: '1d', label: 'Dziś' },
  { value: '7d', label: '7 dni' },
  { value: '30d', label: '30 dni' },
];

type Props = {
  value: Range;
  onChange: (next: Range) => void;
};

export function RangeToggle({ value, onChange }: Props) {
  return (
    <div className="range-toggle" role="group" aria-label="Zakres czasu">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`range-toggle-btn ${value === opt.value ? 'active' : ''}`}
          onClick={() => onChange(opt.value)}
          aria-pressed={value === opt.value}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
