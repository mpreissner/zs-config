import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        zs: {
          50:  "#E6F0FA",
          100: "#CCE1F5",
          500: "#005BAA",
          600: "#004A8A",
          700: "#003A6B",
        },
      },
      keyframes: {
        indeterminate: {
          "0%":   { transform: "translateX(-250%)" },
          "100%": { transform: "translateX(400%)" },
        },
      },
      animation: {
        indeterminate: "indeterminate 1.5s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
