import { copyFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const root = join(import.meta.dirname, "..");
const srcDir = join(root, "node_modules/@electric-sql/pglite/dist");
const destDir = join(root, ".vercel/output/functions/__server.func/_libs");
const marker = join(destDir, "electric-sql__pglite.mjs");
const files = ["pglite.data", "pglite.wasm", "initdb.wasm"];

if (!existsSync(marker)) {
  console.log("[pglite] server bundle has no PGLite chunk; skip asset copy");
  process.exit(0);
}

for (const file of files) {
  const from = join(srcDir, file);
  if (!existsSync(from)) {
    console.error(`[pglite] missing ${from}`);
    process.exit(1);
  }
  copyFileSync(from, join(destDir, file));
}

console.log("[pglite] copied wasm assets next to the server bundle");
