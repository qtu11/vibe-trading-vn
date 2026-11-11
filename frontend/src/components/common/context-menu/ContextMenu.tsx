import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Check, ChevronRight, Circle, Search } from "lucide-react";
import { LoadingSpinner } from "../LoadingSpinner";

// ============================================================================
// 1. CONTEXT & STATE MANAGEMENT
// ============================================================================

interface ContextMenuContextValue {
  isOpen: boolean;
  position: { x: number; y: number };
  openMenu: (e: ReactMouseEvent | MouseEvent | { clientX: number; clientY: number }) => void;
  closeMenu: () => void;
  activeSubmenu: string | null;
  setActiveSubmenu: (id: string | null) => void;
  menuId: string;
}

const ContextMenuContext = createContext<ContextMenuContextValue | null>(null);

export function useContextMenu() {
  const context = useContext(ContextMenuContext);
  if (!context) {
    throw new Error("useContextMenu must be used within a ContextMenu provider");
  }
  return context;
}

// ============================================================================
// 2. ROOT & TRIGGER
// ============================================================================

export interface ContextMenuProps {
  children: ReactNode;
  onOpenChange?: (open: boolean) => void;
}

export function ContextMenu({ children, onOpenChange }: ContextMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [activeSubmenu, setActiveSubmenu] = useState<string | null>(null);
  const menuId = useId();

  const openMenu = useCallback(
    (e: ReactMouseEvent | MouseEvent | { clientX: number; clientY: number }) => {
      // Prevent browser default context menu
      if ("preventDefault" in e) {
        e.preventDefault();
      }
      setPosition({ x: e.clientX, y: e.clientY });
      setIsOpen(true);
      setActiveSubmenu(null);
      onOpenChange?.(true);
    },
    [onOpenChange],
  );

  const closeMenu = useCallback(() => {
    setIsOpen(false);
    setActiveSubmenu(null);
    onOpenChange?.(false);
  }, [onOpenChange]);

  return (
    <ContextMenuContext.Provider
      value={{
        isOpen,
        position,
        openMenu,
        closeMenu,
        activeSubmenu,
        setActiveSubmenu,
        menuId,
      }}
    >
      {children}
    </ContextMenuContext.Provider>
  );
}

export interface ContextMenuTriggerProps extends React.HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  disabled?: boolean;
}

export function ContextMenuTrigger({
  children,
  disabled = false,
  className = "",
  ...props
}: ContextMenuTriggerProps) {
  const { openMenu } = useContextMenu();
  const touchTimer = useRef<number | null>(null);

  const handleContextMenu = (e: ReactMouseEvent) => {
    if (disabled) return;
    openMenu(e);
  };

  // Touch device support (Long press 500ms opens context menu)
  const handleTouchStart = (e: React.TouchEvent) => {
    if (disabled || e.touches.length !== 1) return;
    const touch = e.touches[0];
    const coords = { clientX: touch.clientX, clientY: touch.clientY };

    touchTimer.current = window.setTimeout(() => {
      openMenu(coords);
    }, 520);
  };

  const handleTouchEnd = () => {
    if (touchTimer.current) {
      clearTimeout(touchTimer.current);
      touchTimer.current = null;
    }
  };

  return (
    <div
      onContextMenu={handleContextMenu}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
      onTouchMove={handleTouchEnd}
      className={`select-none ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

// ============================================================================
// 3. MENU CONTENT & VIEWPORT BOUNDARY AWARENESS
// ============================================================================

export interface ContextMenuContentProps {
  children: ReactNode;
  className?: string;
  searchable?: boolean;
  searchPlaceholder?: string;
}

export function ContextMenuContent({
  children,
  className = "",
  searchable = false,
  searchPlaceholder = "Tìm hành động...",
}: ContextMenuContentProps) {
  const { isOpen, position, closeMenu } = useContextMenu();
  const [adjustedPos, setAdjustedPos] = useState({ top: 0, left: 0 });
  const [searchQuery, setSearchQuery] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Auto adjust position against screen edges (Figma/VS Code collision algorithm)
  useEffect(() => {
    if (!isOpen) {
      setSearchQuery("");
      return;
    }

    const adjust = () => {
      if (!menuRef.current) return;
      const rect = menuRef.current.getBoundingClientRect();
      const viewportW = window.innerWidth;
      const viewportH = window.innerHeight;
      const padding = 10;

      let left = position.x;
      let top = position.y;

      // X-Axis collision: flip to left if overflow right
      if (left + rect.width > viewportW - padding) {
        left = Math.max(padding, position.x - rect.width);
      }

      // Y-Axis collision: flip to top if overflow bottom
      if (top + rect.height > viewportH - padding) {
        top = Math.max(padding, position.y - rect.height);
      }

      setAdjustedPos({ top, left });
    };

    // Calculate immediately and on next frame for dynamic height
    adjust();
    const frame = requestAnimationFrame(adjust);
    return () => cancelAnimationFrame(frame);
  }, [isOpen, position]);

  // Click outside & Escape dismiss
  useEffect(() => {
    if (!isOpen) return;

    const handlePointerDown = (e: PointerEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        closeMenu();
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeMenu();
      }
    };

    const handleScroll = () => {
      closeMenu();
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    window.addEventListener("scroll", handleScroll, true);

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("scroll", handleScroll, true);
    };
  }, [isOpen, closeMenu]);

  // Focus search input on open if searchable
  useEffect(() => {
    if (isOpen && searchable) {
      setTimeout(() => searchInputRef.current?.focus(), 40);
    }
  }, [isOpen, searchable]);

  if (!isOpen) return null;

  return createPortal(
    <div
      ref={menuRef}
      role="menu"
      tabIndex={-1}
      aria-orientation="vertical"
      style={{
        position: "fixed",
        top: `${adjustedPos.top}px`,
        left: `${adjustedPos.left}px`,
        zIndex: 99999,
      }}
      className={`vt-pop-in min-w-[200px] max-w-[320px] rounded-[11px] border border-hairline bg-surface-overlay p-1.5 text-ink shadow-lg focus:outline-none select-none text-[13px] font-sans ${className}`}
    >
      {searchable && (
        <div className="relative mb-1 px-1 pt-0.5">
          <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-ink-faint" />
          <input
            ref={searchInputRef}
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={searchPlaceholder}
            className="vt-focus-visible w-full rounded-md border border-hairline-subtle bg-surface-sunken py-1 pl-7 pr-2 text-xs text-ink placeholder:text-ink-faint"
          />
        </div>
      )}
      <div className="flex flex-col gap-0.5">{children}</div>
    </div>,
    document.body,
  );
}

// ============================================================================
// 4. MENU ITEMS & ACTIONS
// ============================================================================

export interface ContextMenuItemProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  icon?: ReactNode;
  shortcut?: string;
  destructive?: boolean;
  disabled?: boolean;
  loading?: boolean;
  onClick?: (e: ReactMouseEvent<HTMLButtonElement>) => void | Promise<void>;
  closeOnClick?: boolean;
}

export function ContextMenuItem({
  children,
  icon,
  shortcut,
  destructive = false,
  disabled = false,
  loading = false,
  onClick,
  closeOnClick = true,
  className = "",
  ...props
}: ContextMenuItemProps) {
  const { closeMenu } = useContextMenu();
  const [internalLoading, setInternalLoading] = useState(false);

  const isExecuting = loading || internalLoading;
  const isInactive = disabled || isExecuting;

  const handleClick = async (e: ReactMouseEvent<HTMLButtonElement>) => {
    if (isInactive) return;
    if (onClick) {
      const result = onClick(e);
      if (result instanceof Promise) {
        setInternalLoading(true);
        try {
          await result;
        } finally {
          setInternalLoading(false);
          if (closeOnClick) closeMenu();
        }
        return;
      }
    }
    if (closeOnClick) closeMenu();
  };

  return (
    <button
      role="menuitem"
      type="button"
      disabled={isInactive}
      onClick={handleClick}
      className={`vt-focus-visible group flex w-full items-center justify-between gap-3 rounded-[7px] px-2.5 py-1.5 text-left text-[13px] font-medium transition-colors duration-fast disabled:cursor-not-allowed ${
        destructive
          ? "text-danger hover:bg-danger/15 focus:bg-danger/15 active:bg-danger/20"
          : "text-ink-secondary hover:bg-muted focus:bg-muted active:bg-muted"
      } ${isInactive ? "opacity-45" : ""} ${className}`}
      {...props}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        {isExecuting ? (
          <LoadingSpinner size={14} className="text-ink-muted" />
        ) : icon ? (
          <span className="flex h-4 w-4 shrink-0 items-center justify-center text-ink-faint group-hover:text-ink-secondary">
            {icon}
          </span>
        ) : (
          <span className="w-4" />
        )}
        <span className="truncate">{children}</span>
      </div>
      {shortcut && <ContextMenuShortcut>{shortcut}</ContextMenuShortcut>}
    </button>
  );
}

// ============================================================================
// 5. CHECKBOX & RADIO ITEMS
// ============================================================================

export interface ContextMenuCheckboxItemProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "checked"> {
  children: ReactNode;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  shortcut?: string;
  closeOnClick?: boolean;
}

export function ContextMenuCheckboxItem({
  children,
  checked,
  onCheckedChange,
  disabled = false,
  shortcut,
  closeOnClick = false,
  className = "",
  ...props
}: ContextMenuCheckboxItemProps) {
  const { closeMenu } = useContextMenu();

  return (
    <button
      role="menuitemcheckbox"
      aria-checked={checked}
      type="button"
      disabled={disabled}
      onClick={() => {
        if (disabled) return;
        onCheckedChange(!checked);
        if (closeOnClick) closeMenu();
      }}
      className={`vt-focus-visible group flex w-full items-center justify-between gap-3 rounded-[7px] px-2.5 py-1.5 text-left text-[13px] font-medium text-ink-secondary transition-colors duration-fast hover:bg-muted focus:bg-muted disabled:cursor-not-allowed disabled:opacity-45 ${className}`}
      {...props}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="flex h-4 w-4 shrink-0 items-center justify-center text-ink">
          {checked ? <Check size={14} className="stroke-[2.5]" /> : null}
        </span>
        <span className="truncate">{children}</span>
      </div>
      {shortcut && <ContextMenuShortcut>{shortcut}</ContextMenuShortcut>}
    </button>
  );
}

export interface ContextMenuRadioItemProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onSelect"> {
  children: ReactNode;
  value: string;
  checked: boolean;
  onSelect: (value: string) => void;
  disabled?: boolean;
}

export function ContextMenuRadioItem({
  children,
  value,
  checked,
  onSelect,
  disabled = false,
  className = "",
  ...props
}: ContextMenuRadioItemProps) {
  const { closeMenu } = useContextMenu();

  return (
    <button
      role="menuitemradio"
      aria-checked={checked}
      type="button"
      disabled={disabled}
      onClick={() => {
        if (disabled) return;
        onSelect(value);
        closeMenu();
      }}
      className={`vt-focus-visible group flex w-full items-center justify-between gap-3 rounded-[7px] px-2.5 py-1.5 text-left text-[13px] font-medium text-ink-secondary transition-colors duration-fast hover:bg-muted focus:bg-muted disabled:cursor-not-allowed disabled:opacity-45 ${className}`}
      {...props}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="flex h-4 w-4 shrink-0 items-center justify-center text-ink">
          {checked ? <Circle size={7} className="fill-current" /> : null}
        </span>
        <span className="truncate">{children}</span>
      </div>
    </button>
  );
}

// ============================================================================
// 6. NESTED SUBMENUS
// ============================================================================

interface SubmenuContextValue {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
}

const SubmenuContext = createContext<SubmenuContextValue | null>(null);

export function ContextMenuSub({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <SubmenuContext.Provider value={{ isOpen, setIsOpen }}>
      <div className="relative w-full">{children}</div>
    </SubmenuContext.Provider>
  );
}

export function ContextMenuSubTrigger({
  children,
  icon,
  disabled = false,
  className = "",
}: {
  children: ReactNode;
  icon?: ReactNode;
  disabled?: boolean;
  className?: string;
}) {
  const subContext = useContext(SubmenuContext);
  const hoverTimeout = useRef<number | null>(null);

  const handlePointerEnter = () => {
    if (disabled || !subContext) return;
    hoverTimeout.current = window.setTimeout(() => {
      subContext.setIsOpen(true);
    }, 110);
  };

  const handlePointerLeave = () => {
    if (hoverTimeout.current) {
      clearTimeout(hoverTimeout.current);
    }
  };

  return (
    <button
      role="menuitem"
      aria-haspopup="menu"
      aria-expanded={subContext?.isOpen}
      disabled={disabled}
      onPointerEnter={handlePointerEnter}
      onPointerLeave={handlePointerLeave}
      className={`vt-focus-visible group flex w-full items-center justify-between gap-3 rounded-[7px] px-2.5 py-1.5 text-left text-[13px] font-medium text-ink-secondary transition-colors duration-fast hover:bg-muted focus:bg-muted disabled:cursor-not-allowed disabled:opacity-45 ${
        subContext?.isOpen ? "bg-muted" : ""
      } ${className}`}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        {icon ? (
          <span className="flex h-4 w-4 shrink-0 items-center justify-center text-ink-faint group-hover:text-ink-secondary">
            {icon}
          </span>
        ) : (
          <span className="w-4" />
        )}
        <span className="truncate">{children}</span>
      </div>
      <ChevronRight size={14} className="shrink-0 text-ink-faint group-hover:text-ink-muted" />
    </button>
  );
}

export function ContextMenuSubContent({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  const subContext = useContext(SubmenuContext);
  const containerRef = useRef<HTMLDivElement>(null);
  const [flipLeft, setFlipLeft] = useState(false);

  useEffect(() => {
    if (!subContext?.isOpen || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    if (rect.right > window.innerWidth - 8) {
      setFlipLeft(true);
    } else {
      setFlipLeft(false);
    }
  }, [subContext?.isOpen]);

  if (!subContext?.isOpen) return null;

  return (
    <div
      ref={containerRef}
      role="menu"
      onPointerLeave={() => subContext.setIsOpen(false)}
      style={{
        position: "absolute",
        top: 0,
        [flipLeft ? "right" : "left"]: "calc(100% + 4px)",
      }}
      className={`vt-pop-in min-w-[180px] max-w-[280px] rounded-[11px] border border-hairline bg-surface-overlay p-1.5 text-ink shadow-lg z-50 flex flex-col gap-0.5 ${className}`}
    >
      {children}
    </div>
  );
}

// ============================================================================
// 7. SEPARATORS, LABELS & SHORTCUTS
// ============================================================================

export function ContextMenuSeparator({ className = "" }: { className?: string }) {
  return <div role="separator" className={`my-1 h-[1px] bg-hairline-subtle ${className}`} />;
}

export function ContextMenuLabel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-ink-faint ${className}`}>
      {children}
    </div>
  );
}

export function ContextMenuShortcut({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={`vt-num text-[11px] font-mono tracking-widest text-ink-faint group-hover:text-ink-muted ${className}`}>
      {children}
    </span>
  );
}
