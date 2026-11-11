import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

/**
 * The surface used by every floating layer (menus, popovers, dropdowns).
 *
 * It owns the elevation treatment so no screen has to re-derive shadows:
 * a hairline ring, a soft drop shadow and a translucent base that lets the
 * content behind it read as "behind".
 */
export function FloatingSurface({
  children,
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-xl border border-hairline bg-surface-overlay/95 text-ink shadow-lg backdrop-blur-xl",
        "vt-pop-in",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

/**
 * A horizontal rule that respects the hairline scale.
 */
export function Divider({
  orientation = "horizontal",
  className,
  ...props
}: { orientation?: "horizontal" | "vertical" } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      role="separator"
      aria-orientation={orientation}
      className={cn(
        "bg-hairline-subtle",
        orientation === "horizontal" ? "h-px w-full" : "h-full w-px",
        className,
      )}
      {...props}
    />
  );
}

/**
 * Focus trap for modal surfaces. Keeps Tab inside the container and restores
 * focus to the previously focused element on unmount.
 */
export function useFocusTrap(
  active: boolean,
  container: React.RefObject<HTMLElement | null>,
  onEscape?: () => void,
) {
  const previous = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!active) return;
    previous.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = container.current;
    const focusable = node?.querySelector<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    focusable?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onEscape?.();
        return;
      }
      if (event.key !== "Tab" || !node) return;
      const items = Array.from(node.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ));
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active_ = document.activeElement;
      if (event.shiftKey && (active_ === first || !node.contains(active_))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active_ === last || !node.contains(active_))) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (previous.current?.isConnected) previous.current.focus();
    };
  }, [active, container, onEscape]);
}
