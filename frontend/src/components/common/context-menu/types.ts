import type { ReactNode } from "react";

export interface ContextMenuPosition {
  x: number;
  y: number;
}

export interface MenuItemData {
  id: string;
  label: string;
  icon?: ReactNode;
  shortcut?: string;
  disabled?: boolean;
  destructive?: boolean;
  loading?: boolean;
  checked?: boolean;
  onClick?: () => void | Promise<void>;
  items?: MenuItemData[]; // For submenus
  separatorBefore?: boolean;
}

export type MenuPlacement = "bottom-right" | "bottom-left" | "top-right" | "top-left";

