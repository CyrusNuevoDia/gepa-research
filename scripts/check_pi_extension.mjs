#!/usr/bin/env node
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const extensionPath = path.join(repoRoot, "pi", "extensions", "gepa-research-path.js");
const expectedBinDir = path.join(repoRoot, "plugins", "gepa-research", "bin");

const extension = await import(pathToFileURL(extensionPath));

if (typeof extension.default !== "function") {
  console.error("ERROR: Pi extension must default-export a function");
  process.exit(1);
}

const originalPath = process.env.PATH ?? "";
try {
  process.env.PATH = originalPath;
  extension.default({});

  const delimiter = path.delimiter;
  const entries = (process.env.PATH ?? "").split(delimiter);

  if (entries[0] !== expectedBinDir) {
    console.error(`ERROR: Pi extension did not prepend ${expectedBinDir} to PATH`);
    process.exit(1);
  }

  extension.default({});
  const count = (process.env.PATH ?? "")
    .split(delimiter)
    .filter((entry) => entry === expectedBinDir).length;

  if (count !== 1) {
    console.error(`ERROR: Pi extension added ${expectedBinDir} to PATH ${count} times`);
    process.exit(1);
  }
} finally {
  process.env.PATH = originalPath;
}

console.log("OK: Pi extension prepends bundled bin directory to PATH");
