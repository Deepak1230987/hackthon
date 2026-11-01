import { documentFileUrl } from "@/lib/api";
import { formatDate, formatDateTime, sourceHost } from "@/lib/provenance";
import type { DocumentView } from "@/lib/types";

const METHOD_TEXT: Record<DocumentView["fetch_method"], string> = {
  http: "Downloaded from the source",
  browser: "Opened in a browser, then downloaded from the source",
  upload: "Uploaded by a user. Not checked against an official site",
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col py-2 sm:flex-row sm:gap-3">
      <dt className="shrink-0 text-muted sm:w-28">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

export function ProvenanceBadge({ document }: { document: DocumentView }) {
  const host = sourceHost(document.source_url);

  return (
    <section aria-labelledby="provenance-heading" className="card p-4 sm:p-5">
      <h2 id="provenance-heading" className="section-title">
        Where this document came from
      </h2>
      <dl className="mt-2 divide-y divide-line text-sm">
        {document.issuing_authority && (
          <Row label="Issued by">{document.issuing_authority}</Row>
        )}
        {host && (
          <Row label="Source">
            <a
              href={document.source_url ?? undefined}
              target="_blank"
              rel="noreferrer"
              className="link inline-flex min-h-11 items-center lg:min-h-0"
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
            className="link inline-flex min-h-11 items-center lg:min-h-0"
          >
            Open our stored copy
          </a>
        </Row>
      </dl>
      <details className="mt-1 border-t border-line pt-2 text-sm">
        <summary className="min-h-11 py-2 text-muted">
          File fingerprint (SHA-256)
        </summary>
        <code className="mt-1 block font-mono text-xs break-all">
          {document.sha256}
        </code>
      </details>
    </section>
  );
}
