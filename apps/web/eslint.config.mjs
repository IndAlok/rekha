import nextVitals from "eslint-config-next/core-web-vitals"

const vitals = Array.isArray(nextVitals) ? nextVitals : [nextVitals]

const eslintConfig = [
  {
    ignores: [".next/**", "node_modules/**", "playwright-report/**", "test-results/**"],
  },
  ...vitals,
  {
    rules: {
      // Next 16's hooks plugin flags mount fetches and fn refs. Those are how the desk loads data.
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/refs": "off",
      "react-hooks/use-memo": "off",
    },
  },
]

export default eslintConfig
