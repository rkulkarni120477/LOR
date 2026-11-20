"use client";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Stack, Typography } from "@mui/material";
import { postJson } from "@/lib/api";
import { PdfPreview } from "@/components/PdfPreview";
export function FilePreview({ id }: { id: string }) {
  const preview = useQuery({
    queryKey: ["file-preview-session", id],
    queryFn: () =>
      postJson<{
        url: string;
        mode: string;
        expires_at: string;
        filename: string;
      }>(`/v1/library/${id}/preview-session`, {}),
    staleTime: 600_000,
    retry: false,
  });
  const value = preview.data;
  return (
    <Stack spacing={2}>
      {preview.isLoading && (
        <Typography role="status">Preparing secure preview…</Typography>
      )}
      {preview.error && <Alert severity="error">{preview.error.message}</Alert>}
      {value && (
        <>
          <Typography variant="body2">{value.filename}</Typography>
          {value.mode === "pdf" ? (
            <PdfPreview url={value.url} />
          ) : value.mode === "video" ? (
            <video
              controls
              preload="metadata"
              src={value.url}
              style={{ width: "100%", maxHeight: 550 }}
            />
          ) : value.mode === "audio" ? (
            <audio
              controls
              preload="metadata"
              src={value.url}
              style={{ width: "100%" }}
            />
          ) : value.mode === "image" ? (
            <img
              alt={value.filename}
              src={value.url}
              style={{ maxWidth: "100%", maxHeight: 600, objectFit: "contain" }}
            />
          ) : (
            <iframe
              title={`Preview: ${value.filename}`}
              src={value.url}
              sandbox="allow-scripts"
              referrerPolicy="no-referrer"
              style={{
                width: "100%",
                height: 560,
                border: "1px solid #dce2eb",
                borderRadius: 8,
              }}
            />
          )}
          {value.mode === "document" && (
            <Typography variant="caption">
              Document text and embedded images. Download the original to
              preserve exact Office layout.
            </Typography>
          )}
          <Button onClick={() => void preview.refetch()}>
            Refresh preview
          </Button>
        </>
      )}
    </Stack>
  );
}
