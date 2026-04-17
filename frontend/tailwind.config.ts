import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["DM Sans", "sans-serif"],
        mono: ["DM Mono", "monospace"],
        display: ["Fraunces", "serif"],
      },
      colors: {
        bg: "#0e0f11",
        bg2: "#141518",
        bg3: "#1a1c20",
        bg4: "#22242a",
        accent: "#6ee7b7",
        accent2: "#818cf8",
        accent3: "#fbbf24",
        danger: "#f87171",
        blue: "#60a5fa",
      },
    },
  },
  plugins: [],
};

export default config;
