import { createHash } from "node:crypto";
import { cp, mkdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = process.cwd();
const source = resolve(root, "portal");
const target = resolve(root, "dist", "portal");

await stat(resolve(source, "index.html"));
await stat(resolve(source, "app.js"));
await stat(resolve(source, "styles.css"));
await rm(target, { recursive: true, force: true });
await mkdir(target, { recursive: true });
await cp(source, target, { recursive: true });

const cacheBustedAssets = ["styles.css", "runtime.css", "app.js", "theme.js"];
let index = await readFile(resolve(target, "index.html"), "utf8");
for (const asset of cacheBustedAssets) {
  const contents = await readFile(resolve(target, asset));
  const digest = createHash("sha256").update(contents).digest("hex").slice(0, 12);
  index = index.replace(`"${asset}"`, `"${asset}?v=${digest}"`);
}
await writeFile(resolve(target, "index.html"), index, "utf8");

console.log(`Portal build ready at ${target}`);
