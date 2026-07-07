export function Sparkline({ values }: { values: number[] }) {
  if (values.length === 0) return <span className="empty">no readings yet</span>;
  const max = Math.max(...values, 1);
  const recent = [...values].reverse().slice(-20);
  return (
    <div className="sparkline">
      {recent.map((v, i) => (
        <div key={i} className="sparkline-bar" style={{ height: `${Math.max((v / max) * 100, 4)}%` }} />
      ))}
    </div>
  );
}
