// Bundle size report: lists every emitted asset (raw + gzip bytes) and writes
// dist/bundle-report.json. Run directly (`pnpm build:report`) or via the Vite
// plugin in vite.config.ts, which calls writeBundleReport after each build.
import { readdirSync, readFileSync, statSync, writeFileSync, existsSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join, relative, resolve, sep } from "node:path";
import { URL, fileURLToPath, pathToFileURL } from "node:url";
import console from "node:console";
import process from "node:process";

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

export function collectBundleReport(distDir) {
  if (!existsSync(distDir)) {
    throw new Error(`Build output not found: ${distDir}. Run "pnpm build" first.`);
  }
  const files = walk(distDir)
    .filter((f) => !f.endsWith("bundle-report.json"))
    .map((f) => {
      const buf = readFileSync(f);
      return {
        file: relative(distDir, f).split(sep).join("/"),
        bytes: buf.length,
        gzipBytes: gzipSync(buf).length,
      };
    })
    .sort((a, b) => b.bytes - a.bytes);
  return {
    totalBytes: files.reduce((n, f) => n + f.bytes, 0),
    totalGzipBytes: files.reduce((n, f) => n + f.gzipBytes, 0),
    files,
  };
}

export function writeBundleReport(distDir) {
  const report = collectBundleReport(distDir);
  const target = join(distDir, "bundle-report.json");
  writeFileSync(target, JSON.stringify(report, null, 2) + "\n");
  return { report, target };
}

const kb = (n) => (n / 1024).toFixed(1) + " kB";

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const distDir = resolve(fileURLToPath(new URL("../dist", import.meta.url)));
  const { report, target } = writeBundleReport(distDir);
  for (const f of report.files) {
    console.log(
      f.file.padEnd(48) + kb(f.bytes).padStart(12) + kb(f.gzipBytes).padStart(12) + " gz",
    );
  }
  console.log(
    "total " + kb(report.totalBytes) + " (" + kb(report.totalGzipBytes) + " gzip) -> " + target,
  );
}
