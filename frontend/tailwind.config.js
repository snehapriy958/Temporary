/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        dark: {
          900: '#0b0f19',
          800: '#111827',
          700: '#1f2937',
          600: '#374151',
        },
        traffic: {
          red: '#ef4444',
          yellow: '#f59e0b',
          green: '#10b981',
          cyan: '#06b6d4',
          purple: '#8b5cf6',
        }
      }
    },
  },
  plugins: [],
}
