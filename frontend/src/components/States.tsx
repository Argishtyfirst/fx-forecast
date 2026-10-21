import { RetryIcon } from "./Icons";

export function Loading({ label = "Loading", height = 160 }: { label?: string; height?: number }) {
  return (
    <div className="state state-loading" style={{ minHeight: height }} role="status" aria-live="polite">
      <span className="loading-bar" aria-hidden="true" />
      <span>{label}&hellip;</span>
    </div>
  );
}

export function ErrorState({
  title = "Could not load this data",
  error,
  onRetry,
}: {
  title?: string;
  error: Error;
  onRetry?: () => void;
}) {
  return (
    <div className="state state-error" role="alert">
      <p className="state-title">{title}</p>
      <p className="state-detail">{error.message}</p>
      {onRetry && (
        <button type="button" className="btn btn-quiet" onClick={onRetry}>
          <RetryIcon size={14} /> Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="state state-empty" data-testid="empty-state">
      <p className="state-title">{title}</p>
      {children && <div className="state-detail">{children}</div>}
    </div>
  );
}
