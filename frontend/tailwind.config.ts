import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#171915",
        graphite: "#555b50",
        mint: "#0f766e",
        coral: "#b42318",
        amber: "#d39b27",
        cloud: "#eef1e8"
      }
    }
  },
  plugins: []
};

export default config;
