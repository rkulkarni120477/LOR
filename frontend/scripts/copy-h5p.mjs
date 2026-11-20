import { cp, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("../", import.meta.url));
await mkdir(`${root}/public/h5p-runtime`, { recursive: true });
await cp(
  `${root}/node_modules/h5p-standalone/dist`,
  `${root}/public/h5p-runtime`,
  { recursive: true },
);
await mkdir(`${root}/public/pdf-runtime`, { recursive: true });
await cp(
  `${root}/node_modules/pdfjs-dist/build/pdf.worker.min.mjs`,
  `${root}/public/pdf-runtime/pdf.worker.min.mjs`,
);
for (const directory of ["cmaps", "standard_fonts", "wasm"]) {
  await cp(
    `${root}/node_modules/pdfjs-dist/${directory}`,
    `${root}/public/pdf-runtime/${directory}`,
    { recursive: true },
  );
}
