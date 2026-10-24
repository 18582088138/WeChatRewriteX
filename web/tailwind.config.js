/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        ink: { 900: '#141414', 700: '#2A2926', 500: '#5F6368', 400: '#6B6B6B' },
        accent: { DEFAULT: '#C63B24', soft: '#FDF0EC', deep: '#A32E1B' },
        paper: '#F9FAFB',
      },
      fontFamily: {
        sans: ['"PingFang SC"', '"Microsoft YaHei"', '"Noto Sans CJK SC"', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        pop: '0 8px 30px rgba(20,20,20,.14)',   // 仅浮动层（弹窗/菜单）
      },
    },
  },
  plugins: [],
}
