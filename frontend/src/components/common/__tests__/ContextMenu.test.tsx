import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  ContextMenu,
  ContextMenuCheckboxItem,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuShortcut,
  ContextMenuTrigger,
} from "../context-menu";

function TestMenuHarness({
  onAction,
  asyncAction,
}: {
  onAction?: () => void;
  asyncAction?: () => Promise<void>;
}) {
  const [checked, setChecked] = useState(false);

  return (
    <ContextMenu>
      <ContextMenuTrigger className="p-4" data-testid="menu-trigger">
        Right click here
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onClick={onAction} shortcut="Ctrl+C">
          Copy Link
        </ContextMenuItem>
        <ContextMenuItem
          onClick={asyncAction}
          data-testid="async-item"
        >
          Export Report
        </ContextMenuItem>
        <ContextMenuItem disabled>Disabled Option</ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuCheckboxItem
          checked={checked}
          onCheckedChange={setChecked}
          data-testid="checkbox-item"
        >
          Pin to Top
        </ContextMenuCheckboxItem>
        <ContextMenuSeparator />
        <ContextMenuItem destructive>Delete</ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

describe("ContextMenu System", () => {
  it("does not render menu content initially", () => {
    render(<TestMenuHarness />);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("opens context menu on right click at trigger", () => {
    render(<TestMenuHarness />);
    const trigger = screen.getByTestId("menu-trigger");

    fireEvent.contextMenu(trigger, { clientX: 120, clientY: 240 });

    const menu = screen.getByRole("menu");
    expect(menu).toBeInTheDocument();
    expect(screen.getByText("Copy Link")).toBeInTheDocument();
    expect(screen.getByText("Ctrl+C")).toBeInTheDocument();
  });

  it("closes on Escape key press", () => {
    render(<TestMenuHarness />);
    const trigger = screen.getByTestId("menu-trigger");

    fireEvent.contextMenu(trigger, { clientX: 100, clientY: 100 });
    expect(screen.getByRole("menu")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("closes when clicking outside the menu", () => {
    render(
      <div>
        <div data-testid="outside">Outside area</div>
        <TestMenuHarness />
      </div>,
    );
    const trigger = screen.getByTestId("menu-trigger");
    fireEvent.contextMenu(trigger, { clientX: 100, clientY: 100 });
    expect(screen.getByRole("menu")).toBeInTheDocument();

    fireEvent.pointerDown(screen.getByTestId("outside"));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("calls onClick and closes menu on item click", async () => {
    const user = userEvent.setup();
    const handleAction = vi.fn();
    render(<TestMenuHarness onAction={handleAction} />);

    const trigger = screen.getByTestId("menu-trigger");
    fireEvent.contextMenu(trigger, { clientX: 100, clientY: 100 });

    const item = screen.getByText("Copy Link");
    await user.click(item);

    expect(handleAction).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("shows LoadingSpinner and disables item during async action execution", async () => {
    let resolvePromise: () => void = () => {};
    const asyncPromise = new Promise<void>((resolve) => {
      resolvePromise = resolve;
    });
    const handleAsyncAction = vi.fn(() => asyncPromise);

    render(<TestMenuHarness asyncAction={handleAsyncAction} />);

    const trigger = screen.getByTestId("menu-trigger");
    fireEvent.contextMenu(trigger, { clientX: 100, clientY: 100 });

    const asyncItem = screen.getByTestId("async-item");
    fireEvent.click(asyncItem);

    expect(handleAsyncAction).toHaveBeenCalledTimes(1);
    // While pending, LoadingSpinner is shown
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(asyncItem).toBeDisabled();

    // Resolve promise
    resolvePromise();
    await waitFor(() => {
      expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    });
  });

  it("toggles checkbox item state without closing menu if closeOnClick=false", () => {
    render(<TestMenuHarness />);

    const trigger = screen.getByTestId("menu-trigger");
    fireEvent.contextMenu(trigger, { clientX: 100, clientY: 100 });

    const checkboxItem = screen.getByTestId("checkbox-item");
    expect(checkboxItem).toHaveAttribute("aria-checked", "false");

    fireEvent.click(checkboxItem);
    expect(checkboxItem).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("does not execute or close menu when clicking disabled item", () => {
    render(<TestMenuHarness />);

    const trigger = screen.getByTestId("menu-trigger");
    fireEvent.contextMenu(trigger, { clientX: 100, clientY: 100 });

    const disabledItem = screen.getByText("Disabled Option").closest("button");
    expect(disabledItem).toBeDisabled();

    fireEvent.click(disabledItem!);
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });
});

