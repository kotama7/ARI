import { useEffect, useRef, useState } from 'react';
import type {
  PDFDocumentLoadingTask,
  PDFDocumentProxy,
  RenderTask,
} from 'pdfjs-dist';
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { useT } from '../../i18n';
import { Button, LoadingState } from '../common';

interface PdfPreviewProps {
  url: string;
  title: string;
}

/**
 * Application-owned PDF preview.
 *
 * Rendering through PDF.js avoids depending on a browser PDF plug-in. This is
 * important for Chromium builds and managed browsers that download PDFs or
 * show an empty iframe instead of providing an embedded viewer.
 */
export function PdfPreview({ url, title }: PdfPreviewProps) {
  const t = useT();
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [hostWidth, setHostWidth] = useState(0);
  const [loading, setLoading] = useState(true);
  const [rendering, setRendering] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const updateWidth = () => setHostWidth(Math.floor(host.clientWidth));
    updateWidth();
    const observer = new ResizeObserver(updateWidth);
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    let loadingTask: PDFDocumentLoadingTask | null = null;
    let loadedPdf: PDFDocumentProxy | null = null;

    setLoading(true);
    setError(null);
    setPdf(null);
    setPageNumber(1);

    void import('pdfjs-dist')
      .then(async (pdfjs) => {
        pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
        loadingTask = pdfjs.getDocument({ url });
        loadedPdf = await loadingTask.promise;
        if (cancelled) {
          await loadedPdf.destroy();
          return;
        }
        setPdf(loadedPdf);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      if (loadedPdf != null) {
        void loadedPdf.destroy();
      } else if (loadingTask != null) {
        void loadingTask.destroy();
      }
    };
  }, [url]);

  useEffect(() => {
    if (pdf == null || hostWidth === 0 || canvasRef.current == null) return;
    let cancelled = false;
    let renderTask: RenderTask | null = null;

    setRendering(true);
    setError(null);
    void pdf
      .getPage(pageNumber)
      .then(async (page) => {
        if (cancelled || canvasRef.current == null) return;
        const base = page.getViewport({ scale: 1 });
        const availableWidth = Math.max(120, hostWidth - 32);
        const fitScale = availableWidth / base.width;
        const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
        const viewport = page.getViewport({
          scale: fitScale * zoom * pixelRatio,
        });
        const canvas = canvasRef.current;
        const context = canvas.getContext('2d', { alpha: false });
        if (context == null) {
          throw new Error(t('pdf_preview_canvas_error'));
        }
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        canvas.style.width = `${Math.floor(viewport.width / pixelRatio)}px`;
        canvas.style.height = `${Math.floor(viewport.height / pixelRatio)}px`;
        renderTask = page.render({ canvas, canvasContext: context, viewport });
        await renderTask.promise;
      })
      .catch((reason: unknown) => {
        if (!cancelled && (reason as { name?: string })?.name !== 'RenderingCancelledException') {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      })
      .finally(() => {
        if (!cancelled) setRendering(false);
      });

    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [hostWidth, pageNumber, pdf, t, zoom]);

  const pageCount = pdf?.numPages ?? 0;
  const zoomPercent = Math.round(zoom * 100);

  return (
    <div className="pdf-preview" ref={hostRef} data-testid="pdf-preview">
      <div className="pdf-preview-toolbar">
        <div className="pdf-preview-paging" role="group" aria-label={t('pdf_preview_pages')}>
          <Button
            variant="outline"
            size="sm"
            disabled={pageNumber <= 1 || loading}
            onClick={() => setPageNumber((current) => Math.max(1, current - 1))}
          >
            {'←'} {t('pdf_preview_previous')}
          </Button>
          <span aria-live="polite">
            {t('pdf_preview_page')} {pageNumber} / {pageCount || '—'}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={pageCount === 0 || pageNumber >= pageCount || loading}
            onClick={() =>
              setPageNumber((current) => Math.min(pageCount, current + 1))
            }
          >
            {t('pdf_preview_next')} {'→'}
          </Button>
        </div>
        <div className="pdf-preview-zoom" role="group" aria-label={t('pdf_preview_zoom')}>
          <Button
            variant="outline"
            size="sm"
            disabled={zoom <= 0.6}
            onClick={() => setZoom((current) => Math.max(0.6, current - 0.2))}
            aria-label={t('pdf_preview_zoom_out')}
          >
            {'−'}
          </Button>
          <span>{zoomPercent}%</span>
          <Button
            variant="outline"
            size="sm"
            disabled={zoom >= 2}
            onClick={() => setZoom((current) => Math.min(2, current + 0.2))}
            aria-label={t('pdf_preview_zoom_in')}
          >
            {'＋'}
          </Button>
        </div>
      </div>

      {loading && (
        <div className="pdf-preview-state">
          <LoadingState inline label={t('pdf_preview_loading')} />
        </div>
      )}
      {error != null && (
        <div className="pdf-preview-state" role="alert">
          <strong>{t('pdf_preview_error')}</strong>
          <span>{error}</span>
          <a href={url} target="_blank" rel="noreferrer">
            {t('pdf_preview_open_original')}
          </a>
        </div>
      )}
      <div className="pdf-preview-scroll" aria-busy={loading || rendering}>
        <canvas
          ref={canvasRef}
          aria-label={`${title} — ${t('pdf_preview_page')} ${pageNumber}`}
        />
      </div>
    </div>
  );
}
