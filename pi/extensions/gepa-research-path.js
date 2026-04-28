import path from "node:path";
import { fileURLToPath } from "node:url";

const extensionDir = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.resolve(extensionDir, "../..");
const bundledBinDir = path.join(packageRoot, "plugins", "gepa-research", "bin");

export default function gepaResearchPathExtension() {
  const currentPath = process.env.PATH ?? "";
  const entries = currentPath.split(path.delimiter);

  if (!entries.includes(bundledBinDir)) {
    process.env.PATH = currentPath
      ? `${bundledBinDir}${path.delimiter}${currentPath}`
      : bundledBinDir;
  }
}
