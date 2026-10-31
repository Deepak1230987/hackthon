import { documentFileUrl } from "@/lib/api";
import {
  formatDate,
  formatDateTime,
  isOldDocument,
  OLD_DOCUMENT_YEARS,
  sourceHost,
} from "@/lib/provenance";
import type { DocumentView } from "@/lib/types";

const METHOD_TEXT: Record<DocumentView["fetch_method"], string> = {
  http: "Downloaded from the source",
  browser: "Opened in a browser, then downloaded from the source",
  upload: "Uploaded by a user. Not checked against an official site",
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col sm:flex-row sm:gap-3">
      <dt className="shrink-0 text-muted sm:w-24">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

export function ProvenanceBadge({ document }: { document: DocumentView }) {
  const host = sourceHost(document.source_url);
  const old = isOldDocument(document.issue_date);

  return (
    <section
      aria-labelledby="provenance-heading"
      className="rounded-lg border border-line bg-surface p-4"
    >
      <h2 id="provenance-heading" className="font-semibold break-words">
        {document.title ?? "Document details"}
      </h2>
      <dl className="mt-3 flex flex-col gap-2 text-sm">
        {document.issuing_authority && (
          <Row label="Issued by">{document.issuing_authority}</Row>
        )}
        {host && (
          <Row label="Source">
            <a
              href={document.source_url ?? undefined}
              target="_blank"
              rel="noreferrer"
              className="text-accent underline"
            >
              {host}
            </a>
          </Row>
        )}
        <Row label="How we got it">{METHOD_TEXT[document.fetch_method]}</Row>
        <Row label="Fetched">{formatDateTime(document.fetched_at)}</Row>
        <Row label="Issue date">
          {document.issue_date
            ? formatDate(document.issue_date)
            : "Not identified"}
        </Row>
        <Row label="Length">
          {document.page_count} {document.page_count === 1 ? "page" : "pages"}
          {document.is_scanned && ", mostly read with OCR"}
        </Row>
        <Row label="File">
          <a
            href={documentFileUrl(document.id)}
            target="_blank"
            rel="noreferrer"
            className="text-accent underline"
          >
            Open our stored copy
          </a>
        </Row>
      </dl>
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer py-1 text-muted">
          File fingerprint (SHA-256)
        </summary>
        <code className="mt-1 block font-mono text-xs break-all">
          {document.sha256}
        </code>
      </details>
      {old && (
        <p className="mt-3 text-sm font-medium text-warning">
          This document was issued more than {OLD_DOCUMENT_YEARS} years ago. The
          rules may have changed, so check the latest version with the issuing
          office.
        </p>
      )}
    </section>
  );
}
