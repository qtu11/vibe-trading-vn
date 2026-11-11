import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * One row of a floating menu.
 *
 * The icon sits in a tinted tile so the menu scans as a list of *actions*
 * rather than a list of words, and the description stays quiet so the title
 * wins the attention.
 */
export function MenuItem({
  icon,
  iconClass = "bg-accent/12 text-accent-ink",
  title,
  description,
  trailing,
  onClick,
  disabled,
  role = "menuitem",
}: {
  icon?: ReactNode;
  iconClass?: string;
  title: ReactNode;
  description?: ReactNode;
  trailing?: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  role?: "menuitem" | "button";
}) {
  return (
    <button
      type="button"
      role={role}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "vt-focus-visible flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors group",
        "hover:bg-muted disabled:pointer-events-none disabled:opacity-40",
      )}
    >
      {icon && (
        <span className={cn(
          "flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-transform group-hover:scale-105",
          iconClass,
        )}>
          {icon}
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-semibold text-ink">{title}</span>
        {description && (
          <span className="block truncate text-[10.5px] text-ink-faint">{description}</span>
        )}
      </span>
      {trailing}
    </button>
  );
}
