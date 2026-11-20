"use client";
import { useEffect, useRef, useState } from "react";
import { Alert, Button, Stack, Typography } from "@mui/material";
export function PdfPreview({ url }: { url: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [page, setPage] = useState(1),
    [pages, setPages] = useState(0);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    let cleanup: (() => void) | undefined;
    setLoading(true);
    setError("");
    void (async () => {
      const pdfjs = await import("pdfjs-dist");
      pdfjs.GlobalWorkerOptions.workerSrc = "/pdf-runtime/pdf.worker.min.mjs";
      const task = pdfjs.getDocument({
        url,
        enableXfa: false,
        cMapUrl: "/pdf-runtime/cmaps/",
        cMapPacked: true,
        standardFontDataUrl: "/pdf-runtime/standard_fonts/",
        wasmUrl: "/pdf-runtime/wasm/",
      });
      cleanup = () => {
        void task.destroy();
      };
      const document = await task.promise;
      if (!active) {
        void task.destroy();
        return;
      }
      setPages(document.numPages);
      const current = await document.getPage(Math.min(page, document.numPages));
      const initial = current.getViewport({ scale: 1 });
      const viewport = current.getViewport({
        scale: Math.min(900 / initial.width, 1.5),
      });
      if (!canvas.current || !active) return;
      canvas.current.height = viewport.height;
      canvas.current.width = viewport.width;
      await current.render({ canvas: canvas.current, viewport }).promise;
      const content = await current.getTextContent();
      if (active) {
        setText(
          content.items
            .map((item) => ("str" in item ? item.str : ""))
            .join(" "),
        );
        setLoading(false);
      }
    })().catch((reason) => {
      if (active) {
        setError(
          reason instanceof Error ? reason.message : "Cannot render this PDF",
        );
        setLoading(false);
      }
    });
    return () => {
      active = false;
      cleanup?.();
    };
  }, [url, page]);
  return (
    <Stack spacing={2}>
      {loading && <Typography role="status">Rendering PDF…</Typography>}
      {error && <Alert severity="error">{error}</Alert>}
      <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
        <Button
          disabled={page <= 1 || loading}
          onClick={() => setPage((p) => p - 1)}
        >
          Previous page
        </Button>
        <Typography aria-live="polite">
          Page {page} of {pages}
        </Typography>
        <Button
          disabled={page >= pages || loading}
          onClick={() => setPage((p) => p + 1)}
        >
          Next page
        </Button>
      </Stack>
      <canvas
        ref={canvas}
        aria-label={`PDF page ${page}`}
        style={{ maxWidth: "100%", height: "auto" }}
      />
      <details>
        <summary>Accessible page text</summary>
        <p>{text || "This page contains no extractable text."}</p>
      </details>
    </Stack>
  );
}
