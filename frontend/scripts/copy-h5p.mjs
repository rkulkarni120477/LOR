import { cp, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("../", import.meta.url));
await mkdir(`${root}/public/h5p-runtime`, {recursive: true});
await cp(`${root}/node_modules/h5p-standalone/dist`, `${root}/public/h5p-runtime`, {recursive: true});
