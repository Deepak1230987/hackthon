"use client";

import { ExternalLink, Minus, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist/legacy/build/pdf.mjs";

import { PagePicker } from "@/components/PagePicker";
import { Notice, Skeleton } from "@/components/ui";
import { documentFileUrl } from "@/lib/api";
import type { Clause } from "@/lib/types";

// Copied here by scripts/copy-pdfjs-assets.mjs.
const ASSETS = "/pdfjs";
const MAX_PIXEL_RATIO = 2;
const ZOOMS = [1, 1.25, 1.5, 2, 3];

type RenderedPage = { page: number; width: number; height: number };

// PDF.js needs browser APIs as soon as it loads, so it can't be imported at the
// top of a file that Next.js also renders on the server.
async function loadPdfjs() {
  const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
  pdfjs.GlobalWorkerOptions.workerSrc = `${ASSETS}/pdf.worker.min.mjs`;
  return pdfjs;
}

export function PdfViewer({
  documentId,
  page,
  pageCount,
  clause,
  onPageChange,
}: {
  documentId: string;
  page: number;
  pageCount: number;
  clause?: Clause;
  onPageChange: (page: number) => void;
}) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const canvasHostRef = useRef<HTMLDivElement>(null);
  const markRef = useRef<HTMLDivElement>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [fitWidth, setFitWidth] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [rendered, setRendered] = useState<RenderedPage | null>(null);
  const width = Math.floor(fitWidth * zoom);

  useEffect(() => {
    let cancelled = false;
    let destroy: (() => void) | undefined;
    void (async () => {
      try {
        const pdfjs = await loadPdfjs();
        if (cancelled) return;
        const task = pdfjs.getDocument({
          url: documentFileUrl(documentId),
          cMapUrl: `${ASSETS}/cmaps/`,
          standardFontDataUrl: `${ASSETS}/standard_fonts/`,
          wasmUrl: `${ASSETS}/wasm/`,
        });
        destroy = () => void task.destroy();
        const loaded = await task.promise;
        if (!cancelled) setPdf(loaded);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      destroy?.();
    };
  }, [documentId, attempt]);

  // The scroller has no width while the mobile sheet is closed, so nothing renders.
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const observer = new ResizeObserver(([entry]) => {
      setFitWidth(Math.floor(entry.contentRect.width));
    });
    observer.observe(scroller);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!pdf || !width) return;
    let cancelled = false;
    let cancelRender: (() => void) | undefined;
    void (async () => {
      try {
        const pdfPage = await pdf.getPage(page);
        if (cancelled) return;
        const base = pdfPage.getViewport({ scale: 1 });
        const ratio = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO);
        const viewport = pdfPage.getViewport({
          scale: (width * ratio) / base.width,
        });
        // A new canvas each time: the old page stays visible until this one is
        // ready, and PDF.js refuses two renders on one canvas.
        const canvas = document.createElement("canvas");
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        canvas.className = "block h-auto w-full";
        const task = pdfPage.render({ canvas, viewport });
        cancelRender = () => task.cancel();
        await task.promise;
        if (cancelled) return;
        canvasHostRef.current?.replaceChildren(canvas);
        setRendered({ page, width: base.width, height: base.height });
      } catch (e) {
        if (!cancelled && (e as Error).name !== "RenderingCancelledException") {
          setFailed(true);
        }
      }
    })();
    return () => {
      cancelled = true;
      cancelRender?.();
    };
  }, [pdf, page, width]);

  const showing = rendered?.page === page ? rendered : null;
  const box = showing && clause?.page === page ? clause.bbox : null;

  useEffect(() => {
    const scroller = scrollerRef.current;
    const stage = stageRef.current;
    const mark = markRef.current;
    if (!scroller || !stage || !showing) return;
    scroller.scrollTop = mark
      ? stage.offsetTop + mark.offsetTop - (scroller.clientHeight - mark.offsetHeight) / 2
      : 0;
    scroller.scrollLeft = mark
      ? stage.offsetLeft + mark.offsetLeft - (scroller.clientWidth - mark.offsetWidth) / 2
      : 0;
  }, [showing, box, zoom]);

  if (failed) {
    return (
      <div className="p-4">
        <Notice tone="danger" role="alert" title="We couldn't show this PDF here.">
          <div className="mt-1 flex flex-wrap gap-4">
            <button
              type="button"
              onClick={() => {
                setFailed(false);
                setPdf(null);
                setAttempt((n) => n + 1);
              }}
              className="link min-h-11"
            >
              Try again
            </button>
            <a
              href={documentFileUrl(documentId)}
              target="_blank"
              rel="noreferrer"
              className="link flex min-h-11 items-center"
            >
              Open the PDF in a new tab
            </a>
          </div>
        </Notice>
      </div>
    );
  }

  const zoomIndex = ZOOMS.indexOf(zoom);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Below the page on a phone, where a thumb can reach it. */}
      <div className="order-last flex flex-wrap items-center justify-between gap-2 border-t border-line bg-surface p-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] lg:order-first lg:border-t-0 lg:border-b lg:pb-2">
        <PagePicker page={page} pageCount={pageCount} onChange={onPageChange} />
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            aria-label="Zoom out"
            disabled={zoomIndex <= 0}
            onClick={() => setZoom(ZOOMS[zoomIndex - 1])}
            className="btn btn-secondary btn-icon"
          >
            <Minus aria-hidden className="size-5" />
          </button>
          <button
            type="button"
            aria-label="Zoom in"
            disabled={zoomIndex >= ZOOMS.length - 1}
            onClick={() => setZoom(ZOOMS[zoomIndex + 1])}
            className="btn btn-secondary btn-icon"
          >
            <Plus aria-hidden className="size-5" />
          </button>
          <a
            href={documentFileUrl(documentId)}
            target="_blank"
            rel="noreferrer"
            aria-label="Open the PDF in a new tab"
            className="btn btn-ghost btn-icon hidden sm:inline-flex"
          >
            <ExternalLink aria-hidden className="size-5" />
          </a>
        </div>
      </div>

      {clause?.page === page && !clause.bbox && (
        <div className="max-h-[35%] shrink-0 overflow-y-auto border-b border-line bg-highlight-soft p-3 text-sm">
          <p className="font-semibold">
            We read this page with OCR, so the exact position can&apos;t be
            marked. Compare this text with the page.
          </p>
          <blockquote lang={clause.lang} className="mt-1 font-display text-base break-words">
            {clause.text}
          </blockquote>
        </div>
      )}

      <div
        ref={scrollerRef}
        // A scrollbar that appeared and vanished would change the width, and so the
        // page height, forever. Keeping its space reserved stops that.
        className="relative min-h-0 flex-1 overflow-auto bg-sunken p-2 [scrollbar-gutter:stable] sm:p-4"
      >
        <div
          ref={stageRef}
          role="img"
          aria-label={`Page ${page} of the document`}
          className="relative mx-auto bg-surface shadow-card"
          style={{
            width: width || undefined,
            aspectRatio: rendered ? `${rendered.width} / ${rendered.height}` : "1 / 1.414",
          }}
        >
          <div ref={canvasHostRef} />
          {!rendered && <Skeleton className="absolute inset-4 rounded-sm" />}
          {box && showing && (
            <div
              key={clause?.id}
              ref={markRef}
              data-testid="clause-highlight"
              className="source-mark pointer-events-none absolute rounded-sm bg-highlight/40 outline-2 outline-offset-1 outline-highlight-strong"
              style={{
                left: `${(box[0] / showing.width) * 100}%`,
                top: `${(box[1] / showing.height) * 100}%`,
                width: `${((box[2] - box[0]) / showing.width) * 100}%`,
                height: `${((box[3] - box[1]) / showing.height) * 100}%`,
              }}
            />
          )}
        </div>
        {!showing && (
          <p role="status" className="sr-only">
            Loading page {page}…
          </p>
        )}
      </div>
    </div>
  );
}
