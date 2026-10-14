// Tailwind generates the utilities the components use (src/tailwind.css). src/index.css is a
// fixed export that only holds the classes used when it was made; a class it lacks would
// otherwise do nothing.
export default {
  plugins: {
    '@tailwindcss/postcss': {},
  },
};
