import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "accent" | "bull" | "bear" | "warning" | "info" | "success" | "danger";

const TONES: Record<Tone, string> = {
  neutral: "border-hairline bg-muted/70 text-ink-secondary",
  accent: "border-accent/25 bg-accent/10 text-accent-ink",
  bull: "border-bull/25 bg-bull/10 text-bull",
  bear: "border-bear/25 bg-bear/10 text-bear",
  warning: "border-warning/25 bg-warning/10 text-warning",
  info: "border-info/25 bg-info/10 text-info",
  success: "border-success/25 bg-success/10 text-success",
  danger: "border-danger/25 bg-danger/10 text-danger",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  size?: "sm" | "md";
  icon?: ReactNode;
  mono?: boolean;
}

export function Badge({
  tone = "neutral",
  size = "sm",
  icon,
  mono,
  className,
  children,
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border font-medium",
        size === "sm" ? "px-1.5 py-px text-[10px]" : "px-2 py-0.5 text-[11px]",
        mono && "vt-num font-mono",
        TONES[tone],
        className,
      )}
      {...props}
    >
      {icon}
      {children}
    </span>
  );
}

/** A small status dot used for run states; it never carries the label itself. */
export function StatusDot({
  tone = "neutral",
  pulse,
  className,
}: {
  tone?: Tone;
  pulse?: boolean;
  className?: string;
}) {
  const colors: Record<Tone, string> = {
    neutral: "bg-ink-faint",
    accent: "bg-accent",
    bull: "bg-bull",
    bear: "bg-bear",
    warning: "bg-warning",
    info: "bg-info",
    success: "bg-success",
    danger: "bg-danger",
  };
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block h-1.5 w-1.5 shrink-0 rounded-full",
        colors[tone],
        pulse && "motion-safe:animate-pulse",
        className,
      )}
    />
  );
}
