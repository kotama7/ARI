interface StatBoxProps {
  value: string | number;
  label: string;
  title?: string;
}

export function StatBox({ value, label, title }: StatBoxProps) {
  return (
    <div className="stat-box" title={title}>
      <div className="stat-val">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
