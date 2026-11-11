import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * A tooltip that stays out of the accessibility tree until it is needed.
 *
 * The trigger keeps a real `aria-describedby` reference only while the tip
 * is visible, so screen readers announce the hint on focus without the tip
 * permanently polluting the DOM.
 */
export function Tooltip({
  label,
  children,
  side = "bottom",
  className,
  disabled,
}: {
  label: ReactNode;
  children: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  className?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const tipId = useId();
  const root = useRef<HTMLSpanElement>(null);
  const timer = useRef(0);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const show = () => {
    if (disabled) return;
    timer.current = window.setTimeout(() => setOpen(true), 260);
  };
  const hide = () => {
    window.clearTimeout(timer.current);
    setOpen(false);
  };

  const position = {
    top: "bottom-full mb-1.5 left-1/2 -translate-x-1/2",
    bottom: "top-full mt-1.5 left-1/2 -translate-x-1/2",
    left: "right-full me-1.5 top-1/2 -translate-y-1/2",
    right: "left-full ms-1.5 top-1/2 -translate-y-1/2",
  }[side];

  return (
    <span
      ref={root}
      className="relative inline-flex"
      onPointerEnter={show}
      onPointerLeave={hide}
      onPointerDown={hide}
    >
      <span aria-describedby={open ? tipId : undefined} className="inline-flex">
        {children}
      </span>
      {open && !disabled && (
        <span
          id={tipId}
          role="tooltip"
          className={cn(
            "vt-pop-in pointer-events-none absolute z-50 whitespace-nowrap rounded-md",
            "border border-hairline bg-surface-overlay px-2 py-1 text-[11px] font-medium text-ink-secondary",
            "shadow-lg",
            position,
            className,
          )}
        >
          {label}
        </span>
      )}
    </span>
  );
}
