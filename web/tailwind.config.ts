import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,html}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace']
      },
      colors: {
        alive: {
          black: '#000000',
          white: '#ffffff',
          dim: '#a3a3a3',
          line: '#ffffff'
        }
      }
    }
  },
  plugins: []
} satisfies Config;
