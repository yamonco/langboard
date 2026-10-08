// Resolve the real Tailwind config before TypeScript checks. The supported
// tailwind-variants transformer generates screen types when the config loads.
import { fileURLToPath } from "node:url";
import loadConfig from "tailwindcss/loadConfig.js";

loadConfig(fileURLToPath(new URL("../tailwind.config.js", import.meta.url)));
