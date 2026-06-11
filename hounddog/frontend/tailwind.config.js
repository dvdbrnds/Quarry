/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          DEFAULT: "#0A1628",
          700: "#162440",
          deep: "#060E1A",
        },
        brass: {
          DEFAULT: "#C5A55A",
          deep: "#9B7E35",
        },
        bone: {
          DEFAULT: "#F5F0E8",
          light: "#FAF8F4",
        },
        ink: {
          DEFAULT: "#1A1A1A",
          mute: "#6B7280",
        },
        signal: {
          green: "#22C55E",
          red: "#EF4444",
        },
      },
    },
  },
  plugins: [],
};
