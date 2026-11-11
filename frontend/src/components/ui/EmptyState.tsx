import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Empty / zero-state surface.
 *
 * Every list in the app (sessions, research sources, tool results) uses this
 * so "nothing here yet" always looks the same and always offers a way out.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
  compact,
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed border-hairline",
        "bg-surface-panel/50 text-center",
        compact ? "gap-1.5 px-4 py-6" : "gap-2.5 px-6 py-10",
        className,
      )}
    >
      {icon && (
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted text-ink-muted">
          {icon}
        </span>
      )}
      <p className={cn("font-medium text-ink-secondary", compact ? "text-xs" : "text-sm")}>{title}</p>
      {description && (
        <p className="max-w-sm text-xs leading-relaxed text-ink-muted">{description}</p>
      )}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

/**
 * A shimmering placeholder block. Used instead of spinners wherever the
 * final shape of the content is already known.
 */
export function Skeleton({
  className,
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      aria-hidden="true"
      className={cn("vt-skeleton rounded-md bg-muted/60", className)}
      style={style}
    />
  );
}

export function SkeletonMetrics() {
  return (
    <div className="grid grid-cols-3 gap-1.5 p-3">
      {Array.from({ length: 6 }).map((_, index) => (
        <div key={index} className="flex flex-col items-center gap-1.5 py-2">
          <Skeleton className="h-2 w-10" />
          <Skeleton className="h-4 w-14" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonChart({ height = 300 }: { height?: number }) {
  return <Skeleton className="w-full" style={{ height }} />;
}
