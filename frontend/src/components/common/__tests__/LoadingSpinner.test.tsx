import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LoadingSpinner } from "../LoadingSpinner";

describe("LoadingSpinner", () => {
  it("renders with role status and default accessible label", () => {
    render(<LoadingSpinner />);
    const spinner = screen.getByRole("status", { name: "Đang tải..." });
    expect(spinner).toBeInTheDocument();
    expect(spinner).toHaveAttribute("viewBox", "0 0 24 24");
    expect(spinner.classList.contains("animate-spin")).toBe(true);
  });

  it("supports predefined size keys (xs, sm, md, lg)", () => {
    const { rerender } = render(<LoadingSpinner size="xs" />);
    let spinner = screen.getByRole("status");
    expect(spinner).toHaveAttribute("width", "14");
    expect(spinner).toHaveAttribute("height", "14");

    rerender(<LoadingSpinner size="lg" />);
    spinner = screen.getByRole("status");
    expect(spinner).toHaveAttribute("width", "24");
    expect(spinner).toHaveAttribute("height", "24");
  });

  it("supports custom numeric pixel size", () => {
    render(<LoadingSpinner size={32} />);
    const spinner = screen.getByRole("status");
    expect(spinner).toHaveAttribute("width", "32");
    expect(spinner).toHaveAttribute("height", "32");
  });

  it("allows custom aria-label and additional classes", () => {
    render(<LoadingSpinner label="Loading items" className="text-zinc-400 custom-class" />);
    const spinner = screen.getByRole("status", { name: "Loading items" });
    expect(spinner.classList.contains("custom-class")).toBe(true);
    expect(spinner.classList.contains("text-zinc-400")).toBe(true);
  });

  it("renders both background track and rotating foreground arc", () => {
    const { container } = render(<LoadingSpinner />);
    const circles = container.querySelectorAll("circle");
    expect(circles.length).toBe(2);
    // Background track
    expect(circles[0]).toHaveAttribute("r", "9");
    expect(circles[0].classList.contains("opacity-20")).toBe(true);
    // Foreground spinning arc
    expect(circles[1]).toHaveAttribute("r", "9");
    expect(circles[1]).toHaveAttribute("stroke-dasharray", "42 56.5");
    expect(circles[1].classList.contains("opacity-90")).toBe(true);
  });
});

