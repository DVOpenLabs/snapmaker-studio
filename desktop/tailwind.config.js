/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        ready: "hsl(var(--ready))",
        repairable: "hsl(var(--repairable))",
        convertible: "hsl(var(--convertible))",
        risk: "hsl(var(--risk))",
      },
      textColor: {
        primary: { DEFAULT: "hsl(var(--primary-text))", foreground: "hsl(var(--primary-foreground))" },
        ready: "hsl(var(--ready-text))",
        repairable: "hsl(var(--repairable-text))",
        risk: "hsl(var(--risk-text))",
      },
      borderRadius: { lg: "12px", md: "8px", sm: "6px" },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
