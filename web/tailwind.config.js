/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        ink: {
          900: '#0f172a', 700: '#334155', 500: '#64748b', 400: '#94a3b8',
        },
        accent: {
          DEFAULT: '#2563eb', soft: '#eff4ff', deep: '#1e40af',
        },
        paper: '#f5f6f8',
      },
      fontFamily: {
        sans: ['"PingFang SC"', '"Microsoft YaHei"', '"Noto Sans CJK SC"', 'system-ui', 'sans-serif'],
      },
      borderRadius: { xl2: '1rem' },
      boxShadow: {
        card: '0 1px 3px rgba(15,23,42,.06), 0 4px 14px rgba(15,23,42,.04)',
        pop: '0 8px 30px rgba(15,23,42,.12)',
      },
    },
  },
  plugins: [],
}
