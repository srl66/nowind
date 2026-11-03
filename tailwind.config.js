/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{vue,ts}"],
  theme: {
    extend: {
      colors: {
        canvas: "rgb(var(--c-canvas) / <alpha-value>)",
        surface: "rgb(var(--c-surface) / <alpha-value>)",
        sidebar: "rgb(var(--c-sidebar) / <alpha-value>)",
        ink: "rgb(var(--c-ink) / <alpha-value>)",
        muted: "rgb(var(--c-muted) / <alpha-value>)",
        line: "rgb(var(--c-line) / <alpha-value>)",
        accent: "rgb(var(--c-accent) / <alpha-value>)",
        "accent-soft": "rgb(var(--c-accent-soft) / <alpha-value>)",
        danger: "rgb(var(--c-danger) / <alpha-value>)",
      },
      boxShadow: {
        soft: "0 1px 2px rgb(0 0 0 / 0.04), 0 12px 32px -16px rgb(0 0 0 / 0.22)",
        bubble: "0 1px 2px rgb(0 0 0 / 0.05)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        blink: {
          "0%, 80%, 100%": { opacity: "0.25" },
          "40%": { opacity: "1" },
        },
      },
      animation: {
        "fade-up": "fade-up .22s ease-out both",
        "fade-in": "fade-in .18s ease-out both",
        blink: "blink 1.2s infinite",
      },
    },
  },
  plugins: [],
};
