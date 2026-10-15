// Makes the browser actually save a real file the backend returned (a
// `text/csv` response with `Content-Disposition: attachment`), rather than
// navigating to it or rendering its text inline. Standard
// createObjectURL + synthetic-anchor-click pattern; the object URL is
// revoked right after the click is dispatched since the download itself
// is already queued by then.
export function triggerBrowserDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
