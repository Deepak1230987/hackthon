"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist/legacy/build/pdf.mjs";

import { PagePicker } from "@/components/PagePicker";
import { documentFileUrl } from "@/lib/api";
import type { Clause } from "@/lib/types";

// Copied here by scripts/copy-pdfjs-assets.mjs.
const ASSETS = "/pdfjs";
const MAX_PIXEL_RATIO = 2;

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
  const [width, setWidth] = useState(0);
  const [rendered, setRendered] = useState<RenderedPage | null>(null);

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

  // The stage has no width while the mobile sheet is closed, so nothing renders.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const observer = new ResizeObserver(([entry]) => {
      setWidth(Math.floor(entry.contentRect.width));
    });
    observer.observe(stage);
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
    const mark = markRef.current;
    if (!scroller || !showing) return;
    scroller.scrollTop = mark
      ? mark.offsetTop - (scroller.clientHeight - mark.offsetHeight) / 2
      : 0;
  }, [showing, box]);

  if (failed) {
    return (
      <div role="alert" className="p-4 text-sm">
        <p className="text-danger">We couldn&apos;t show this PDF here.</p>
        <div className="mt-2 flex flex-wrap gap-4">
          <button
            type="button"
            onClick={() => {
              setFailed(false);
              setPdf(null);
              setAttempt((n) => n + 1);
            }}
            className="min-h-11 font-semibold text-accent underline"
          >
            Try again
          </button>
          <a
            href={documentFileUrl(documentId)}
            target="_blank"
            rel="noreferrer"
            className="flex min-h-11 items-center font-semibold text-accent underline"
          >
            Open the PDF in a new tab
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-center border-b border-line p-2">
        <PagePicker page={page} pageCount={pageCount} onChange={onPageChange} />
      </div>

      {clause?.page === page && !clause.bbox && (
        <div className="max-h-[35%] shrink-0 overflow-y-auto border-b border-line bg-highlight-soft p-3 text-sm">
          <p className="font-semibold">
            We read this page with OCR, so the exact position can&apos;t be
            marked. Compare this text with the page.
          </p>
          <blockquote lang={clause.lang} className="mt-1 break-words">
            {clause.text}
          </blockquote>
        </div>
      )}

      <div
        ref={scrollerRef}
        // A scrollbar that appeared and vanished would change the width, and so the
        // page height, forever. Keeping its space reserved stops that.
        className="relative min-h-0 flex-1 overflow-y-auto bg-line/40 [scrollbar-gutter:stable]"
      >
        <div
          ref={stageRef}
          role="img"
          aria-label={`Page ${page} of the document`}
          className="relative bg-surface"
          style={
            rendered
              ? { aspectRatio: `${rendered.width} / ${rendered.height}` }
              : undefined
          }
        >
          <div ref={canvasHostRef} />
          {box && showing && (
            <div
              ref={markRef}
              data-testid="clause-highlight"
              className="pointer-events-none absolute rounded-sm bg-highlight/40 outline-2 outline-offset-1 outline-highlight-strong"
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
          <p role="status" className="p-4 text-center text-sm text-muted">
            Loading page {page}…
          </p>
        )}
      </div>
    </div>
  );
}
