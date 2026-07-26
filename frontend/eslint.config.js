// Configuración plana (ESLint 9). Sólo usa los paquetes ya declarados en package.json:
// @typescript-eslint/parser y @typescript-eslint/eslint-plugin — sin añadir dependencias.
import tsPlugin from "@typescript-eslint/eslint-plugin";
import tsParser from "@typescript-eslint/parser";

export default [
  {
    ignores: ["dist/**", "node_modules/**", "../dist/**"],
  },
  {
    files: ["src/**/*.ts", "tests/**/*.ts"],
    languageOptions: {
      parser: tsParser,
      ecmaVersion: 2022,
      sourceType: "module",
      parserOptions: {
        project: "./tsconfig.json",
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "@typescript-eslint": tsPlugin,
    },
    rules: {
      // El motor de patrones es código validado por veterinarios: lo que se persigue aquí son
      // fallos silenciosos (variables muertas, promesas sin await, comparaciones laxas), no estilo.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/await-thenable": "error",
      // En "error": todo el trabajo asíncrono pasa por `manejadorAsync`/`sinEsperar` (async.ts),
      // que reportan el rechazo en el toast, o por un `void` explícito cuando la función ya
      // absorbe su error a propósito. Un handler `async` suelto vuelve a tragar fallos en
      // silencio, así que debe romper el lint.
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": "error",
      "@typescript-eslint/no-explicit-any": "warn",
      eqeqeq: ["error", "always", { null: "ignore" }],
      "no-var": "error",
      "prefer-const": "error",
      // `console.log` filtró prompts con datos de paciente en el ia.js legacy; se avisa para que
      // no vuelva a entrar. warn/error siguen permitidos.
      "no-console": ["warn", { allow: ["warn", "error"] }],
    },
  },
];
