import { cn } from "@/lib/utils";

export type SpinnerSize = "xs" | "sm" | "md" | "lg" | number;

export interface LoadingSpinnerProps extends React.SVGAttributes<SVGSVGElement> {
  size?: SpinnerSize;
  className?: string;
  label?: string;
}

const SIZE_MAP: Record<string, number> = {
  xs: 14,
  sm: 16,
  md: 18,
  lg: 24,
};

/**
 * The app's single loading indicator.
 *
 * Two arcs: a faint full track plus a bright leading arc with a rounded
 * cap. Rotation is 750ms and is disabled under reduced-motion, where the
 * arc simply stops rather than disappearing.
 */
export function LoadingSpinner({
  size = "md",
  className = "",
  label = "Đang tải...",
  ...props
}: LoadingSpinnerProps) {
  const pixelSize = typeof size === "number" ? size : SIZE_MAP[size] ?? 18;

  return (
    <svg
      role="status"
      aria-label={label}
      viewBox="0 0 24 24"
      width={pixelSize}
      height={pixelSize}
      className={cn(
        "inline-block shrink-0 animate-spin motion-reduce:animate-none",
        className,
      )}
      style={{ width: pixelSize, height: pixelSize, animationDuration: "750ms" }}
      {...props}
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.8"
        className="opacity-20"
      />
      <circle
        cx="12"
        cy="12"
        r="9"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.8"
        strokeLinecap="round"
        strokeDasharray="42 56.5"
        className="opacity-90"
      />
    </svg>
  );
}
