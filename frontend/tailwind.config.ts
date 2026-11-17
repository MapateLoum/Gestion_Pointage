import type { Config } from "tailwindcss";

const withAlpha = (name: string) => `hsl(var(--${name}) / <alpha-value>)`;

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: withAlpha("background"),
        foreground: withAlpha("foreground"),
        card: withAlpha("card"),
        muted: withAlpha("muted"),
        "muted-foreground": withAlpha("muted-foreground"),
        border: withAlpha("border"),
        ring: withAlpha("ring"),
        primary: withAlpha("primary"),
        "primary-foreground": withAlpha("primary-foreground"),
        accent: withAlpha("accent"),
        "accent-foreground": withAlpha("accent-foreground"),
        destructive: withAlpha("destructive"),
        "destructive-foreground": withAlpha("destructive-foreground"),
        success: withAlpha("success"),
        warning: withAlpha("warning"),
        sidebar: withAlpha("sidebar"),
        "sidebar-foreground": withAlpha("sidebar-foreground"),
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
      },
      boxShadow: {
        soft: "0 1px 2px hsl(var(--foreground) / 0.04), 0 4px 16px hsl(var(--foreground) / 0.06)",
      },
    },
  },
  plugins: [],
};

export default config;
