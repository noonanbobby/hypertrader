import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        background: "#0a0e1a",
        card: "#111827",
        "card-border": "rgba(255,255,255,0.05)",
        accent: {
          green: "#00ff88",
          red: "#ff4444",
          blue: "#3b82f6",
        },
        "text-primary": "#f1f5f9",
        "text-secondary": "#94a3b8",
      },
      animation: {
        "flash-green": "flashGreen 0.5s ease-out",
        "flash-red": "flashRed 0.5s ease-out",
        "fade-in": "fadeIn 0.3s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
      },
      keyframes: {
        flashGreen: {
          "0%": { backgroundColor: "rgba(0, 255, 136, 0.3)" },
          "100%": { backgroundColor: "transparent" },
        },
        flashRed: {
          "0%": { backgroundColor: "rgba(255, 68, 68, 0.3)" },
          "100%": { backgroundColor: "transparent" },
        },
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
