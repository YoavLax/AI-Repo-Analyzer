import type { Config } from "tailwindcss";

// CodeCompass design tokens — Untitled-UI direction (plan-v3-codecompass.md §4).
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        primary: {
          25: "#FCFAFF",
          50: "#F9F5FF",
          100: "#F4EBFF",
          200: "#E9D7FE",
          300: "#D6BBFB",
          400: "#B692F6",
          500: "#9E77ED",
          600: "#7F56D9",
          700: "#6941C6",
          800: "#53389E",
          900: "#42307D",
        },
        gray: {
          25: "#FCFCFD",
          50: "#F9FAFB",
          100: "#F2F4F7",
          200: "#EAECF0",
          300: "#D0D5DD",
          400: "#98A2B3",
          500: "#667085",
          600: "#475467",
          700: "#344054",
          800: "#1D2939",
          900: "#101828",
        },
        // Dark-mode surfaces (class strategy).
        night: {
          page: "#0C111D",
          card: "#161B26",
          border: "#1F242F",
          text: "#F5F5F6",
          muted: "#94969C",
        },
        brandblue: "#2970FF",
        success: { 50: "#ECFDF3", 500: "#12B76A", 700: "#027A48" },
        warning: { 50: "#FFFAEB", 500: "#F79009", 700: "#B54708" },
        danger: { 50: "#FEF3F2", 500: "#F04438", 700: "#B42318" },
      },
      fontFamily: {
        sans: ["Inter Variable", "Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      backgroundImage: {
        // Signature 45deg blue-to-violet gradient.
        brand: "linear-gradient(45deg, #2970FF 0%, #7F56D9 100%)",
        "brand-hover": "linear-gradient(45deg, #1B5FE8 0%, #6941C6 100%)",
      },
      boxShadow: {
        card: "0 1px 2px 0 rgba(16, 24, 40, 0.05)",
        "card-md":
          "0 4px 8px -2px rgba(16, 24, 40, 0.10), 0 2px 4px -2px rgba(16, 24, 40, 0.06)",
      },
    },
  },
  plugins: [],
} satisfies Config;
