import { useEffect, useRef, useState } from "react";
import { Menu, X } from "lucide-react";
import { Link, useLocation } from "react-router";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { isNavigationActive, NAVIGATION_GROUPS } from "./navigation";

export function SidebarNavigation({ collapsed }: { collapsed: boolean }) {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);

  useEffect(() => { setMenuOpen(false); }, [pathname, collapsed]);
  useEffect(() => {
    if (!menuOpen) return;
    panelRef.current?.querySelector<HTMLElement>("a")?.focus();
    const close = () => setMenuOpen(false);
    const dismiss = (event: MouseEvent) => {
      if (!panelRef.current?.contains(event.target as Node)
        && !triggerRef.current?.contains(event.target as Node)) close();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        close();
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", dismiss);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", dismiss);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", close);
    };
  }, [menuOpen]);

  const groups = (compact: boolean, drawer = false) => NAVIGATION_GROUPS.map(({ id, items }) => (
    <section
      key={id}
      aria-label={t(`navigation.groups.${id}`)}
      className={cn(id !== "research" && "border-t border-hairline-subtle pt-3 mt-3")}
    >
      {!compact && (
        <p
          className={cn(
            "mb-1.5 px-2.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-faint",
            !drawer && "max-md:hidden",
          )}
        >
          {t(`navigation.groups.${id}`)}
        </p>
      )}
      <div className="space-y-0.5">
        {items.map(({ id: itemId, to, icon: Icon }) => {
          const label = t(`layout.${itemId}`);
          const active = isNavigationActive(to, pathname);
          return (
            <Link
              key={to}
              to={to}
              aria-label={label}
              aria-current={active ? "page" : undefined}
              title={`${label} — ${t(`navigation.descriptions.${itemId}`)}`}
              onClick={() => setMenuOpen(false)}
              className={cn(
                "group relative flex items-center rounded-lg text-[13px] transition-[background-color,color] duration-[--dur-fast] ease-standard",
                "vt-focus-visible",
                compact ? "justify-center px-2 py-2" : "gap-2.5 px-2.5 py-[7px]",
                !compact && !drawer && "max-md:justify-center max-md:px-2",
                active
                  ? "bg-accent/10 font-medium text-accent-ink shadow-[inset_0_0_0_1px_hsl(var(--accent)/0.16)]"
                  : "text-ink-secondary hover:bg-muted/70 hover:text-ink",
              )}
            >
              {/* Active rail: a single accent bar on the inline-start edge. */}
              <span
                aria-hidden="true"
                className={cn(
                  "pointer-events-none absolute inset-y-1.5 start-0 w-[2px] rounded-full bg-accent transition-opacity duration-[--dur-fast]",
                  active ? "opacity-100" : "opacity-0",
                )}
              />
              <span
                aria-hidden="true"
                className={cn(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-colors duration-[--dur-fast]",
                  active
                    ? "bg-accent/12 text-accent"
                    : "text-ink-faint group-hover:bg-muted group-hover:text-ink-secondary",
                )}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
              </span>
              {!compact && (
                <span className={cn("min-w-0 truncate", !drawer && "max-md:hidden")}>{label}</span>
              )}
            </Link>
          );
        })}
      </div>
    </section>
  ));

  return (
    <>
      <nav
        aria-label={t("layout.mainNavigation")}
        className={cn("shrink-0 space-y-3 overflow-y-auto", collapsed ? "p-1" : "p-2 max-md:p-1")}
      >
        <button
          ref={triggerRef}
          type="button"
          aria-label={t("navigation.menu")}
          title={t("navigation.menu")}
          aria-expanded={menuOpen}
          aria-controls="sidebar-feature-menu"
          onClick={() => setMenuOpen((open) => !open)}
          className={cn(
            "vt-focus-visible flex w-full justify-center rounded-md border border-hairline p-2",
            "text-ink-muted transition-colors hover:bg-muted hover:text-ink",
            !collapsed && "md:hidden",
          )}
        >
          <Menu className="h-4 w-4" aria-hidden="true" />
        </button>
        {groups(collapsed)}
      </nav>
      {menuOpen && (
        <nav
          ref={panelRef}
          id="sidebar-feature-menu"
          aria-label={t("navigation.menu")}
          className={cn(
            "vt-pop-in fixed inset-y-0 start-12 z-40 w-[min(18rem,calc(100vw-3rem))]",
            "space-y-3 overflow-y-auto border-e border-hairline bg-surface-sidebar p-3 shadow-lg",
          )}
        >
          <div className="flex items-center justify-between px-2.5 py-1 text-[13px] font-semibold text-ink">
            {t("navigation.menu")}
            <button
              type="button"
              aria-label={t("navigation.close")}
              onClick={() => { setMenuOpen(false); triggerRef.current?.focus(); }}
              className="vt-focus-visible rounded p-1.5 text-ink-muted transition-colors hover:bg-muted hover:text-ink"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
          {groups(false, true)}
        </nav>
      )}
    </>
  );
}
