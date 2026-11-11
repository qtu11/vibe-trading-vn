import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, Outlet, useLocation, useSearchParams } from "react-router";
import { Check, ChevronDown, Languages, Moon, Plus, Search, Sun, Trash2, Pencil, MessageSquare, ChevronsLeft, ChevronsRight, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDarkMode } from "@/hooks/useDarkMode";
import { api, type SessionItem } from "@/lib/api";
import { safeGet, safeSet } from "@/lib/storage";
import { useAgentStore } from "@/stores/agent";
import { BrandMark } from "@/components/common/BrandMark";
import { ConnectionBanner } from "@/components/layout/ConnectionBanner";
import { SUPPORTED_LANGUAGES } from "@/i18n";
import i18n from "@/i18n";
import { toast } from "sonner";
import { SidebarNavigation } from "./SidebarNavigation";
import { PageHelp } from "./PageHelp";
import { NAVIGATION_GROUPS } from "./navigation";

// APP_VERSION is sourced from i18n locale files (app.version key) to keep a
// single source of truth across the footer and every localised README.

export function Layout() {
  const { t } = useTranslation();

  const { pathname } = useLocation();
  const [searchParams] = useSearchParams();
  const { dark, toggle } = useDarkMode();
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const sessionsLoadGeneration = useRef(0);
  const pendingSessionActions = useRef(new Set<string>());
  const sseStatus = useAgentStore(s => s.sseStatus);
  const sseRetryAttempt = useAgentStore(s => s.sseRetryAttempt);
  const [collapsed, setCollapsed] = useState(() => safeGet("qa-sidebar") === "collapsed");
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const sessionsPanelRef = useRef<HTMLDivElement>(null);
  const sessionsTriggerRef = useRef<HTMLButtonElement>(null);

  const activeSessionId = searchParams.get("session");
  const streamingSessionId = useAgentStore(s => s.streamingSessionId);

  useEffect(() => {
    if (!sessionsOpen) return;
    const dismiss = (event: MouseEvent) => {
      if (!sessionsPanelRef.current?.contains(event.target as Node)
        && !sessionsTriggerRef.current?.contains(event.target as Node)) setSessionsOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSessionsOpen(false);
        sessionsTriggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", dismiss);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", dismiss);
      document.removeEventListener("keydown", onKey);
    };
  }, [sessionsOpen]);

  useEffect(() => {
    safeSet("qa-sidebar", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  useEffect(() => {
    const syncSidebarPreference = (event: StorageEvent) => {
      if (event.key !== null && event.key !== "qa-sidebar") return;
      setCollapsed(safeGet("qa-sidebar") === "collapsed");
    };
    window.addEventListener("storage", syncSidebarPreference);
    return () => window.removeEventListener("storage", syncSidebarPreference);
  }, []);

  const loadSessions = useCallback(() => {
    const generation = ++sessionsLoadGeneration.current;
    setSessionsLoading(true);
    api.listSessions()
      .then((list) => {
        if (generation !== sessionsLoadGeneration.current) return;
        setSessions(Array.isArray(list) ? list : []);
        setSessionsError(null);
      })
      .catch((error: unknown) => {
        if (generation === sessionsLoadGeneration.current) {
          setSessionsError(error instanceof Error ? error.message : i18n.t("settings.unknownError"));
        }
      })
      .finally(() => {
        if (generation === sessionsLoadGeneration.current) setSessionsLoading(false);
      });
  }, []);

  // Load sessions on mount. Also refresh when navigating TO /agent or when
  // the active session changes (covers new session creation from Agent).
  const isAgentPage = pathname === "/" || pathname.startsWith("/agent");
  useEffect(() => {
    loadSessions();
    return () => { sessionsLoadGeneration.current += 1; };
  }, [isAgentPage, activeSessionId, loadSessions]);

  // Re-list after out-of-band title changes (e.g. LLM auto-titling on the
  // first completed exchange).
  useEffect(() => {
    const refresh = () => loadSessions();
    window.addEventListener("vibe:sessions-refresh", refresh);
    return () => window.removeEventListener("vibe:sessions-refresh", refresh);
  }, [loadSessions]);

  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const deleteSession = async (sid: string) => {
    if (pendingSessionActions.current.has(sid)) return;
    pendingSessionActions.current.add(sid);
    try {
      await api.deleteSession(sid);
      setSessions((prev) => prev.filter((s) => s.session_id !== sid));
      setDeleteTarget(null);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("settings.unknownError"));
    } finally {
      pendingSessionActions.current.delete(sid);
    }
  };

  const renameSession = async (sid: string) => {
    if (!renameValue.trim()) { setRenameTarget(null); return; }
    if (pendingSessionActions.current.has(sid)) return;
    pendingSessionActions.current.add(sid);
    const title = renameValue.trim();
    try {
      await api.renameSession(sid, title);
      setSessions((prev) => prev.map((s) => s.session_id === sid ? { ...s, title } : s));
      setRenameTarget(null);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("settings.unknownError"));
    } finally {
      pendingSessionActions.current.delete(sid);
    }
  };

  return (
    <div className="flex h-screen bg-surface text-ink rtl:flex-row-reverse">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:start-4 focus:top-4 focus:z-[70] focus:rounded-md focus:bg-surface-overlay focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-ink focus:shadow-lg focus:outline-none focus:ring-2 focus:ring-accent/40"
      >
        {t('layout.skipToMain', { defaultValue: 'Skip to main content' })}
      </a>
      {/* Sidebar */}
      <aside
        aria-label={t('layout.sidebar', { defaultValue: 'Vibe-Trading sidebar' })}
        className={cn(
          "w-12 border-e border-hairline bg-surface-sidebar flex flex-col shrink-0 transition-[width] duration-[--dur-base] ease-standard overflow-visible z-30",
          !collapsed && "md:w-64"
        )}
      >
        {/* Brand */}
        <div className={cn(
          "border-b border-hairline-subtle vt-edge-bottom",
          collapsed ? "p-2 flex justify-center" : "px-3 py-3 max-md:p-2 max-md:flex max-md:justify-center",
        )}>
          <Link
            to="/"
            aria-label="Vibe-Trading"
            className={cn(
              "vt-focus-visible flex items-center group",
              collapsed ? "justify-center" : "gap-2.5 max-md:justify-center",
            )}
          >
            <BrandMark className="h-8 w-8 shrink-0 transition-transform duration-[--dur-fast] group-hover:scale-105" priority />
            {!collapsed && (
              <div className="flex flex-col min-w-0 max-md:hidden">
                <span className="text-[15px] font-semibold tracking-tight text-ink leading-tight">
                  Vibe-Trading
                </span>
                <span className="text-[10px] font-semibold text-accent-ink/85 tracking-[0.14em] uppercase">
                  AI Trading Lab
                </span>
              </div>
            )}
          </Link>
        </div>

        {/* Nav */}
        <SidebarNavigation collapsed={collapsed} />

        <button
          ref={sessionsTriggerRef}
          type="button"
          aria-label={t("layout.sessions")}
          aria-expanded={sessionsOpen}
          aria-controls="sidebar-sessions"
          title={t("layout.sessions")}
          onClick={() => setSessionsOpen((open) => !open)}
          className={cn(
            "vt-focus-visible mx-1 mt-2 flex items-center justify-center rounded-md border-t p-2",
            "text-ink-muted transition-colors hover:bg-muted hover:text-ink",
            !collapsed && "md:hidden",
          )}
        >
          <MessageSquare className="h-4 w-4" />
        </button>

        {/* Compact layouts keep history and new-chat actions in a disclosure. */}
        {(!collapsed || sessionsOpen) && (
          <div
            ref={sessionsPanelRef}
            id="sidebar-sessions"
            aria-label={t("layout.sessions")}
            className={cn(
              "overflow-auto flex flex-col border-hairline",
              sessionsOpen
                ? "fixed inset-y-0 start-12 z-40 w-[min(18rem,calc(100vw-3rem))] border-e bg-surface-sidebar shadow-lg"
                : "flex-1 border-t mt-2 max-md:hidden",
            )}
          >
            <div className="flex items-center justify-between px-3.5 py-2">
              <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-faint">
                <MessageSquare className="h-3.5 w-3.5" />
                {t('layout.sessions')}
              </span>
              <Link
                to="/agent"
                onClick={() => setSessionsOpen(false)}
                aria-label={t('layout.newChat')}
                className="vt-focus-visible flex items-center gap-1 rounded p-1.5 text-ink-muted transition-colors hover:bg-muted hover:text-ink"
                title={t('layout.newChat')}
              >
                <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
              {sessionsOpen && (
                <button
                  type="button"
                  aria-label={t("layout.collapse")}
                  onClick={() => { setSessionsOpen(false); sessionsTriggerRef.current?.focus(); }}
                  className="vt-focus-visible rounded p-1.5 text-ink-muted transition-colors hover:bg-muted hover:text-ink"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>

            {sessionsOpen && sessionsError && (
              <div className="mx-3 mb-3 rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs">
                <p>{t("layout.sessionsLoadFailed")} {sessionsError}</p>
                <button
                  type="button"
                  onClick={loadSessions}
                  disabled={sessionsLoading}
                  className="mt-2 rounded border border-hairline px-2 py-1 disabled:opacity-50"
                >
                  {t("connection.retry")}
                </button>
              </div>
            )}

            <div className="px-2 pb-2 space-y-0.5 overflow-auto flex-1">
              {sessionsLoading ? (
                <div className="space-y-1.5 px-2 py-1">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-7 rounded-md bg-muted/60 animate-pulse" />
                  ))}
                </div>
              ) : !sessionsError && sessions.length === 0 ? (
                <p className="px-3 py-2 text-xs text-ink-faint">{t('layout.noSessions')}</p>
              ) : null}
              {sessions.map((s) => {
                const isActive = s.session_id === activeSessionId;
                const isDeleting = deleteTarget === s.session_id;
                const isRenaming = renameTarget === s.session_id;
                return (
                  <div key={s.session_id} className="group relative flex items-center">
                    {isRenaming ? (
                      <input
                        autoFocus
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") renameSession(s.session_id); if (e.key === "Escape") setRenameTarget(null); }}
                        onBlur={() => renameSession(s.session_id)}
                        aria-label={`${t('layout.rename')}: ${s.title || s.session_id}`}
                        className="flex-1 min-w-0 ps-3 pe-2 py-1.5 rounded-md text-xs border border-accent bg-surface-panel outline-none focus:ring-2 focus:ring-primary/40"
                      />
                    ) : (
                      <Link
                        to={`/agent?session=${s.session_id}`}
                        onClick={() => setSessionsOpen(false)}
                        className={cn(
                          "flex-1 min-w-0 ps-3 pe-14 py-1.5 rounded-md text-xs transition-colors truncate block border-s-2",
                          isActive
                            ? "border-s-accent bg-accent/10 text-accent-ink font-medium"
                            : "border-s-transparent text-ink-secondary hover:bg-muted hover:text-ink",
                        )}
                        title={s.title || s.session_id}
                      >
                        <span className="flex min-w-0 items-center gap-1.5">
                          {streamingSessionId === s.session_id ? (
                            <Loader2 className="h-3 w-3 shrink-0 animate-spin text-accent" />
                          ) : (
                            // Transparent placeholder keeps titles aligned with
                            // spinner rows without a meaningless gray dot.
                            <span className={cn(
                              "h-1.5 w-1.5 rounded-full shrink-0",
                              isActive ? "bg-accent" : "bg-transparent",
                            )}
                            />
                          )}
                          <span className="min-w-0 truncate">{s.title || s.session_id.slice(0, 16)}</span>
                        </span>
                      </Link>
                    )}
                    {!isRenaming && isDeleting ? (
                      <div className="absolute right-0.5 flex items-center gap-0.5">
                        <button onClick={() => deleteSession(s.session_id)} className="p-1.5 text-danger hover:bg-danger/10 rounded text-[10px] font-medium">{t('layout.confirm')}</button>
                        <button onClick={() => setDeleteTarget(null)} className="p-1.5 text-ink-muted hover:bg-muted rounded text-[10px]">{t('layout.cancel')}</button>
                      </div>
                    ) : !isRenaming ? (
                      <div className="absolute right-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 flex items-center gap-0.5 transition-opacity">
                        <button
                          onClick={(e) => { e.preventDefault(); e.stopPropagation(); setRenameTarget(s.session_id); setRenameValue(s.title || ""); }}
                          className="p-1.5 text-ink-muted hover:text-ink rounded"
                          title={t('layout.rename')}
                        >
                          <Pencil className="h-3 w-3" />
                        </button>
                        <button
                          onClick={(e) => { e.preventDefault(); e.stopPropagation(); setDeleteTarget(s.session_id); }}
                          className="p-1.5 text-ink-muted hover:text-danger rounded"
                          title={t('layout.delete')}
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Spacer when collapsed */}
        {collapsed && <div className="flex-1" />}

        {/* Footer */}
        <div className={cn(
          "mt-auto border-t border-hairline-subtle",
          collapsed
            ? "p-1 flex flex-col items-center gap-1"
            : "p-3 space-y-2 max-md:p-1 max-md:flex max-md:flex-col max-md:items-center max-md:gap-1 max-md:space-y-0",
        )}>
          {collapsed ? (
            <>
              <button onClick={toggle} className="vt-focus-visible p-1.5 text-ink-muted hover:text-ink rounded transition-colors" title={dark ? t('layout.light') : t('layout.dark')}>
                {dark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
              </button>
              <button onClick={() => setCollapsed(false)} className="vt-focus-visible p-1.5 text-ink-muted hover:text-ink rounded transition-colors" title={t('layout.expand')}>
                <ChevronsRight className="h-3.5 w-3.5" />
              </button>
              <LanguageSwitcher compact />
            </>
          ) : (
            <>
              <div className="flex items-center justify-between max-md:flex-col">
                <button
                  onClick={toggle}
                  className="vt-focus-visible flex items-center gap-1.5 p-1.5 text-xs text-ink-muted hover:text-ink transition-colors"
                >
                  {dark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
                  <span className="max-md:hidden">{dark ? t('layout.light') : t('layout.dark')}</span>
                </button>
                <div className="flex items-center gap-1 max-md:hidden">
                  <button
                    onClick={() => setCollapsed(true)}
                    className="vt-focus-visible p-1.5 text-ink-muted hover:text-ink rounded transition-colors"
                    title={t('layout.collapse')}
                  >
                    <ChevronsLeft className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <div className="flex flex-col gap-1 max-md:items-center">
                <LanguageSwitcher />
                {/* About is marketing, not a work surface — it lives here by
                    the version stamp instead of in the primary nav. */}
                <div className="flex items-center gap-1.5 text-[10px] text-ink-faint max-md:hidden">
                  <span>{t('app.version')}</span>
                  <span aria-hidden="true">·</span>
                  <Link to="/about" className="transition-colors hover:text-ink">
                    {t('layout.about')}
                  </Link>
                </div>
              </div>
            </>
          )}
        </div>
      </aside>

      {/* Main */}
      <div className="relative flex-1 flex flex-col overflow-hidden vt-workspace">
        <CommandBar pathname={pathname} collapsed={collapsed} onToggleSidebar={() => setCollapsed((value) => !value)} />
        {sessionsError ? (
          <div role="alert" className="flex flex-wrap items-center gap-2 border-b border-warning/30 bg-warning/10 px-4 py-2 text-xs">
            <span className="font-medium">{t("layout.sessionsLoadFailed")}</span>
            <span className="text-ink-muted">{sessionsError}</span>
            <button type="button" onClick={loadSessions} disabled={sessionsLoading} className="ms-auto rounded-md border border-hairline px-2 py-1 disabled:opacity-50">
              {sessionsLoading ? t("settings.loading") : t("connection.retry")}
            </button>
            <Link to="/settings" className="text-accent-ink underline">{t("layout.settings")}</Link>
          </div>
        ) : <ConnectionBanner status={sseStatus} retryAttempt={sseRetryAttempt} />}
        <main id="main" className="flex-1 min-h-0 overflow-auto">
          <PageHelp />
          <Outlet />
        </main>
      </div>
    </div>
  );
}

/**
 * The application command bar.
 *
 * A desktop-native shell needs one persistent strip that answers three
 * questions at a glance: where am I, what can I jump to, and is the system
 * healthy. The bar is intentionally thin and frosted so it frames the
 * workspace instead of competing with it.
 */
function CommandBar({
  pathname,
  collapsed,
  onToggleSidebar,
}: {
  pathname: string;
  collapsed: boolean;
  onToggleSidebar: () => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const activeItem = useMemo(() => {
    for (const group of NAVIGATION_GROUPS) {
      const match = group.items.find((item) =>
        item.to === "/"
          ? pathname === "/" || pathname.startsWith("/agent")
          : pathname === item.to || pathname.startsWith(`${item.to}/`),
      );
      if (match) return match;
    }
    return undefined;
  }, [pathname]);

  const results = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const all = NAVIGATION_GROUPS.flatMap((group) =>
      group.items.map((item) => ({ group, item })),
    );
    if (!needle) return all.slice(0, 8);
    return all
      .filter(({ item }) => {
        const label = t(`layout.${item.id}`);
        return label.toLowerCase().includes(needle)
          || item.to.toLowerCase().includes(needle);
      })
      .slice(0, 8);
  }, [query, t]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    const onClick = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  return (
    <header className="vt-chrome vt-edge-bottom relative z-30 flex h-12 shrink-0 items-center gap-2 border-b border-hairline-subtle px-3 md:px-4">
      <button
        type="button"
        onClick={onToggleSidebar}
        aria-label={collapsed ? t("layout.expand") : t("layout.collapse")}
        title={collapsed ? t("layout.expand") : t("layout.collapse")}
        className="vt-focus-visible flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-muted hover:text-ink"
      >
        {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
      </button>

      {/* Breadcrumb — the current location in the product. */}
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-xs">
        <span className="hidden shrink-0 font-medium uppercase tracking-[0.12em] text-ink-faint sm:inline">
          {t("app.name", { defaultValue: "Workspace" })}
        </span>
        <span aria-hidden="true" className="hidden shrink-0 text-ink-faint/60 sm:inline">/</span>
        <span className="truncate font-medium text-ink">
          {activeItem ? t(`layout.${activeItem.id}`) : t("layout.home")}
        </span>
      </nav>

      <div className="ms-auto flex items-center gap-2">
        {/* Command palette trigger — searches the product's surfaces. */}
        <div ref={rootRef} className="relative hidden md:block">
          <div className="relative flex h-8 w-56 items-center">
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute start-2.5 h-3.5 w-3.5 text-ink-faint"
            />
            <input
              type="search"
              value={query}
              onFocus={() => setOpen(true)}
              onChange={(event) => {
                setQuery(event.target.value);
                setOpen(true);
              }}
              placeholder={t("layout.commandSearch", { defaultValue: "Search…" })}
              aria-label={t("layout.commandSearch", { defaultValue: "Search" })}
              className={cn(
                "vt-focus-visible h-8 w-full rounded-lg border border-hairline bg-surface-sunken/60 ps-8 pe-12",
                "text-xs text-ink placeholder:text-ink-faint",
                "transition-colors duration-fast hover:border-hairline-strong focus:bg-surface-panel",
              )}
            />
            <kbd className="pointer-events-none absolute end-2 rounded border border-hairline bg-surface-panel px-1.5 py-0.5 font-mono text-[10px] text-ink-faint">
              /
            </kbd>
          </div>
          {open && (
            <div
              className="vt-floating vt-pop-in absolute end-0 top-full mt-2 w-72 overflow-hidden rounded-xl"
              role="listbox"
              aria-label={t("layout.commandSearch", { defaultValue: "Search" })}
            >
              <ul className="max-h-80 overflow-y-auto p-1.5">
                {results.map(({ group, item }) => (
                  <li key={item.to}>
                    <Link
                      to={item.to}
                      role="option"
                      aria-selected={false}
                      onClick={() => {
                        setOpen(false);
                        setQuery("");
                      }}
                      className="vt-focus-visible flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-xs text-ink-secondary transition-colors hover:bg-muted hover:text-ink"
                    >
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-accent/10 text-accent-ink">
                        <item.icon className="h-3.5 w-3.5" aria-hidden="true" />
                      </span>
                      <span className="min-w-0 flex-1 truncate">
                        {t(`layout.${item.id}`)}
                      </span>
                      <span className="shrink-0 text-[10px] text-ink-faint">
                        {t(`navigation.groups.${group.id}`)}
                      </span>
                    </Link>
                  </li>
                ))}
                {results.length === 0 && (
                  <li className="px-2.5 py-3 text-xs text-ink-faint">
                    {t("layout.commandEmpty", { defaultValue: "No matching surfaces." })}
                  </li>
                )}
              </ul>
            </div>
          )}
        </div>

        {/* Live system status — a calm, always-present health signal. */}
        <span
          className="hidden items-center gap-1.5 rounded-full border border-hairline bg-surface-sunken/60 px-2.5 py-1 text-[10.5px] font-medium text-ink-muted lg:inline-flex"
          title={t("layout.systemStatus", { defaultValue: "Workspace services" })}
        >
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-60" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-success" />
          </span>
          {t("layout.systemOnline", { defaultValue: "Online" })}
        </span>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------------
// Language switcher — dropdown listing every language registered in
// src/i18n/index.ts. Persists the choice via i18next's localStorage detector
// and emits the `languageChanged` event handled in the i18n module to flip
// <html dir/lang> for RTL languages.
//
// Positioning: the menu uses `position: fixed` and is placed at
// `(triggerLeft, triggerTop - gap)`. This bypasses every ancestor's
// `overflow: hidden/auto/scroll`, stacking contexts, and CSS direction
// rules, so the dropdown is *always* fully visible regardless of where
// the trigger sits in the layout or which language is active. We measure
// the trigger with getBoundingClientRect() and update on resize/scroll.
// ---------------------------------------------------------------------------
function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  const { i18n, t } = useTranslation();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [menuStyle, setMenuStyle] = useState<{ left: number; bottom: number; minWidth: number } | null>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent | TouchEvent) => {
      if (
        triggerRef.current &&
        !triggerRef.current.contains(e.target as Node) &&
        !(e.target as HTMLElement).closest?.("[data-lang-menu]")
      ) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("touchstart", onClick, { passive: true });
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("touchstart", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Recompute the menu's fixed coordinates whenever it opens, or whenever
  // the viewport changes (resize / scroll / language switch). The menu is
  // anchored to the trigger's *left edge* and sits *above* the trigger.
  useEffect(() => {
    if (!open || !triggerRef.current) return;
    const place = () => {
      const r = triggerRef.current?.getBoundingClientRect();
      if (!r) return;
      // Anchor: align the menu's right edge with the trigger's right edge,
      // then clamp to the viewport so the menu never overflows the screen.
      const menuWidth = 160; // px — approx longest label "العربية" + padding
      const gap = 4; // mb-1
      const desiredLeft = r.right - menuWidth;
      const maxLeft = window.innerWidth - menuWidth - 8;
      const minLeft = 8;
      const left = Math.max(minLeft, Math.min(maxLeft, desiredLeft));
      setMenuStyle({
        left,
        // distance from viewport bottom: viewport height − trigger top + gap
        bottom: window.innerHeight - r.top + gap,
        minWidth: menuWidth,
      });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);

  // i18n.language (singular) is the primary active language. We try an exact
  // match first against SUPPORTED_LANGUAGES. If that fails (e.g. a regional
  // variant like "ja-JP"), we fall back to i18n.languages (plural) which
  // includes both the detected and resolved codes. NOTE: i18n.languages
  // always contains the fallback language ("en"), so it must NOT be the
  // primary match — otherwise "en" being first in SUPPORTED_LANGUAGES
  // would always win and the switcher would never show any other language.
  const current =
    SUPPORTED_LANGUAGES.find((l) => l.code === i18n.language) ??
    SUPPORTED_LANGUAGES.find((l) => i18n.languages?.includes(l.code)) ??
    SUPPORTED_LANGUAGES[0];

  return (
    <div>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={t("layout.language")}
        className="vt-focus-visible flex items-center gap-1 p-1.5 text-xs text-ink-muted hover:text-ink transition-colors max-md:justify-center"
      >
        <Languages className="h-3.5 w-3.5 shrink-0" />
        {!compact && <span className="whitespace-nowrap max-md:hidden">{current.label}</span>}
        {!compact && <ChevronDown className={cn("h-3 w-3 shrink-0 transition-transform max-md:hidden", open && "rotate-180")} />}
      </button>
      {open && menuStyle && (
        <ul
          data-lang-menu
          aria-label="Select language"
          style={{
            position: "fixed",
            left: menuStyle.left,
            bottom: menuStyle.bottom,
            minWidth: menuStyle.minWidth,
            zIndex: 60,
          }}
          className="vt-pop-in rounded-xl border border-hairline bg-surface-overlay shadow-lg"
        >
          {SUPPORTED_LANGUAGES.map((lang) => {
            const active = lang.code === current.code;
            return (
              <li key={lang.code}>
                <button
                  type="button"
                  onClick={() => {
                    i18n.changeLanguage(lang.code).catch(console.error);
                    setOpen(false);
                  }}
                  aria-current={active || undefined}
                  className={cn(
                    "vt-focus-visible w-full flex items-center gap-2 px-2.5 py-1.5 text-xs hover:bg-muted hover:text-ink transition-colors",
                    active && "text-ink font-medium",
                  )}
                >
                  <span className="flex-1 text-start whitespace-nowrap">{lang.label}</span>
                  {active && <Check className="h-3 w-3 shrink-0 text-accent" />}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
