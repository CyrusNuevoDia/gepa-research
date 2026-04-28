import path from "node:path";
import { fileURLToPath } from "node:url";

const extensionDir = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.resolve(extensionDir, "../..");
const bundledBinDir = path.join(packageRoot, "plugins", "gepa-research", "bin");

// Pi invokes default-exported extension factories during startup, before tools
// spawn subprocesses. The ExtensionAPI argument is intentionally unused here:
// the only setup needed is making the bundled CLI wrappers visible on PATH.
export default function gepaResearchPathExtension(_api) {
  const currentPath = process.env.PATH ?? "";
  const entries = currentPath.split(path.delimiter);

  if (!entries.includes(bundledBinDir)) {
    process.env.PATH = currentPath
      ? `${bundledBinDir}${path.delimiter}${currentPath}`
      : bundledBinDir;
  }
}
