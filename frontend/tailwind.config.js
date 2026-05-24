/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        base: '#08080F',
        surface: '#0F0F1C',
        card: '#141428',
        elevated: '#1C1C34',
        border: '#252540',
        gold: {
          300: '#E8CC82',
          400: '#D4AF61',
          500: '#B8932A',
          600: '#8C6E1E',
        },
        ink: {
          primary: '#EEE8DC',
          secondary: '#9A96A8',
          muted: '#5C5A70',
        },
        navy: {
          900: '#0A1625',
          800: '#111F35',
          700: '#1A2E4A',
          600: '#243D61',
          500: '#2E4E7A',
        },
        forest: {
          700: '#1C3528',
          600: '#274D38',
          500: '#326448',
          400: '#4A8060',
          300: '#6A9E7E',
        },
        wine: {
          700: '#3D1520',
          600: '#561E2D',
          500: '#72283C',
          400: '#904E60',
        },
        cream: '#EDE8DC',
        parchment: '#C8BFA8',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        display: ['"Playfair Display"', 'Georgia', 'serif'],
      },
      boxShadow: {
        gold: '0 0 20px rgba(212,175,97,0.12)',
        'gold-lg': '0 0 40px rgba(212,175,97,0.18)',
        card: '0 4px 24px rgba(0,0,0,0.4)',
      },
      backgroundImage: {
        'gold-gradient': 'linear-gradient(135deg, #D4AF61 0%, #E8CC82 50%, #B8932A 100%)',
        'surface-gradient': 'linear-gradient(180deg, #0F0F1C 0%, #08080F 100%)',
      },
    },
  },
  plugins: [],
}
