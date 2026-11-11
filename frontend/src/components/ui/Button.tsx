import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "outline" | "danger" | "subtle";
type Size = "xs" | "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent text-accent-foreground shadow-xs hover:bg-accent-strong active:translate-y-px disabled:hover:bg-accent",
  secondary:
    "bg-surface-raised text-ink border border-hairline shadow-xs hover:bg-surface-overlay hover:border-hairline-strong active:translate-y-px",
  outline:
    "border border-hairline text-ink-secondary hover:text-ink hover:bg-muted/70 hover:border-hairline-strong",
  ghost:
    "text-ink-secondary hover:text-ink hover:bg-muted/80 active:bg-muted",
  subtle:
    "bg-muted text-ink-secondary hover:bg-muted/70 hover:text-ink",
  danger:
    "bg-danger text-white shadow-xs hover:brightness-95 active:translate-y-px",
};

const SIZES: Record<Size, string> = {
  xs: "h-6 px-2 text-[11px] gap-1 rounded-sm",
  sm: "h-7 px-2.5 text-xs gap-1.5 rounded-md",
  md: "h-8 px-3 text-[13px] gap-1.5 rounded-md",
  lg: "h-10 px-4 text-sm gap-2 rounded-lg",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  /** Renders the button as an icon-only control with a square hit area. */
  icon?: boolean;
  leading?: ReactNode;
  trailing?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", icon, leading, trailing, className, children, type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "vt-focus-visible inline-flex select-none items-center justify-center whitespace-nowrap font-medium",
        "transition-[background-color,border-color,color,box-shadow,transform] duration-[--dur-fast] ease-standard",
        "disabled:pointer-events-none disabled:opacity-40",
        icon ? (size === "lg" ? "h-10 w-10" : size === "md" ? "h-8 w-8" : size === "sm" ? "h-7 w-7" : "h-6 w-6") : SIZES[size],
        !icon && SIZES[size],
        VARIANTS[variant],
        className,
      )}
      {...props}
    >
      {leading}
      {children}
      {trailing}
    </button>
  );
});

export interface IconButtonProps extends Omit<ButtonProps, "children" | "icon"> {
  label: string;
  icon: ReactNode;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, icon, variant = "ghost", size = "md", className, ...props },
  ref,
) {
  return (
    <Button
      ref={ref}
      variant={variant}
      size={size}
      icon
      aria-label={label}
      title={label}
      className={cn("shrink-0", className)}
      {...props}
    >
      {icon}
    </Button>
  );
});
