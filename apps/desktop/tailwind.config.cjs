/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class", '[data-theme="dark"]'],
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        cortex: {
          bg: "var(--bg)",
          surface: "var(--surface)",
          "surface-2": "var(--surface-2)",
          "surface-hover": "var(--surface-hover)",
          border: "var(--border)",
          "border-2": "var(--border-2)",
          text: "var(--text)",
          muted: "var(--text-muted)",
          subtle: "var(--text-subtle)",
          accent: "var(--accent)",
          "accent-2": "var(--accent-2)",
          good: "var(--good)",
          warn: "var(--warn)",
          bad: "var(--bad)",
        },
      },
      fontFamily: {
        sans: "var(--font-sans)",
        serif: "var(--font-serif)",
        mono: "var(--font-mono)",
      },
    },
  },
  plugins: [],
};

