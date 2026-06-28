interface LoadingProps {
  label?: string;
}

export function Loading({ label = "불러오는 중..." }: LoadingProps) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
