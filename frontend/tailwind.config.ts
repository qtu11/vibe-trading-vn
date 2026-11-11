import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Elevation ladder. Each step is visually distinct from its
        // neighbour; `surface` is the single entry point for app chrome.
        surface: {
          sunken: "hsl(var(--surface-sunken) / <alpha-value>)",
          DEFAULT: "hsl(var(--surface-base) / <alpha-value>)",
          sidebar: "hsl(var(--surface-sidebar) / <alpha-value>)",
          panel: "hsl(var(--surface-panel) / <alpha-value>)",
          raised: "hsl(var(--surface-raised) / <alpha-value>)",
          overlay: "hsl(var(--surface-overlay) / <alpha-value>)",
          chrome: "hsl(var(--surface-chrome) / <alpha-value>)",
        },
        // Hairlines in three strengths.
        hairline: {
          subtle: "hsl(var(--border-subtle) / <alpha-value>)",
          DEFAULT: "hsl(var(--border) / <alpha-value>)",
          strong: "hsl(var(--border-strong) / <alpha-value>)",
        },
        // Ink in four levels.
        ink: {
          DEFAULT: "hsl(var(--ink) / <alpha-value>)",
          secondary: "hsl(var(--ink-secondary) / <alpha-value>)",
          muted: "hsl(var(--ink-muted) / <alpha-value>)",
          faint: "hsl(var(--ink-faint) / <alpha-value>)",
          inverse: "hsl(var(--ink-inverse) / <alpha-value>)",
        },
        // Brand accent.
        accent: {
          DEFAULT: "hsl(var(--accent) / <alpha-value>)",
          strong: "hsl(var(--accent-strong) / <alpha-value>)",
          ink: "hsl(var(--accent-ink) / <alpha-value>)",
          soft: "hsl(var(--accent-soft) / <alpha-value>)",
          foreground: "hsl(var(--accent-foreground) / <alpha-value>)",
        },
        // Market + workflow semantics.
        bull: { DEFAULT: "hsl(var(--bull) / <alpha-value>)", soft: "hsl(var(--bull-soft) / <alpha-value>)" },
        bear: { DEFAULT: "hsl(var(--bear) / <alpha-value>)", soft: "hsl(var(--bear-soft) / <alpha-value>)" },
        info: { DEFAULT: "hsl(var(--info) / <alpha-value>)", soft: "hsl(var(--info-soft) / <alpha-value>)" },
        // The crimson identity used on generated research documents.
        report: {
          brand: "hsl(var(--report-brand) / <alpha-value>)",
          ink: "hsl(var(--report-brand-ink) / <alpha-value>)",
          soft: "hsl(var(--report-brand-soft) / <alpha-value>)",
          strong: "hsl(var(--report-brand-ink-strong) / <alpha-value>)",
          card: {
            from: "hsl(var(--report-card-from) / <alpha-value>)",
            via: "hsl(var(--report-card-via) / <alpha-value>)",
            to: "hsl(var(--report-card-to) / <alpha-value>)",
          },
        },

        // Legacy aliases — existing utilities keep working.
        border: "hsl(var(--border) / <alpha-value>)",
        background: "hsl(var(--background) / <alpha-value>)",
        foreground: "hsl(var(--foreground) / <alpha-value>)",
        muted: { DEFAULT: "hsl(var(--muted) / <alpha-value>)", foreground: "hsl(var(--muted-foreground) / <alpha-value>)" },
        primary: { DEFAULT: "hsl(var(--primary) / <alpha-value>)", foreground: "hsl(var(--primary-foreground) / <alpha-value>)" },
        destructive: { DEFAULT: "hsl(var(--destructive) / <alpha-value>)", foreground: "hsl(var(--destructive-foreground) / <alpha-value>)" },
        card: { DEFAULT: "hsl(var(--card) / <alpha-value>)", foreground: "hsl(var(--card-foreground) / <alpha-value>)" },
        popover: { DEFAULT: "hsl(var(--popover) / <alpha-value>)", foreground: "hsl(var(--popover-foreground) / <alpha-value>)" },
        success: "hsl(var(--success) / <alpha-value>)",
        danger: "hsl(var(--danger) / <alpha-value>)",
        warning: "hsl(var(--warning) / <alpha-value>)",
      },
      boxShadow: {
        xs: "var(--shadow-sm)",
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
        xl: "var(--shadow-lg)",
        "2xl": "var(--shadow-lg)",
        float: "var(--shadow-float)",
        panel: "var(--shadow-panel)",
        brand: "var(--shadow-brand)",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        xs: "calc(var(--radius) - 6px)",
      },
      transitionTimingFunction: {
        standard: "var(--ease-standard)",
        emphasized: "var(--ease-emphasized)",
      },
      transitionDuration: {
        instant: "var(--dur-instant)",
        fast: "var(--dur-fast)",
        base: "var(--dur-base)",
        slow: "var(--dur-slow)",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        // Display serif for the hero greeting only — system stack, no webfont.
        // Deliberately NOT used for answers/tables (numeric content stays sans/mono).
        serif: ["Times New Roman", "Georgia", "serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      keyframes: {
        "fade-rise": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "pop-in": {
          from: { opacity: "0", transform: "translateY(4px) scale(0.985)" },
          to: { opacity: "1", transform: "translateY(0) scale(1)" },
        },
        shimmer: {
          from: { backgroundPosition: "180% 0" },
          to: { backgroundPosition: "-80% 0" },
        },
      },
      animation: {
        "fade-rise": "fade-rise var(--dur-base) var(--ease-standard) both",
        "pop-in": "pop-in var(--dur-fast) var(--ease-standard) both",
      },
    },
  },
  plugins: [typography],
} satisfies Config;
