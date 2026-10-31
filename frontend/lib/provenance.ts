export const OLD_DOCUMENT_YEARS = 5;

const DATE = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

const DATE_TIME = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
  timeZoneName: "short",
});

// issue_date is a plain calendar date, so it mustn't shift with the time zone.
export function formatDate(isoDate: string): string {
  return DATE.format(new Date(`${isoDate}T00:00:00Z`));
}

export function formatDateTime(isoDateTime: string): string {
  return DATE_TIME.format(new Date(isoDateTime));
}

export function sourceHost(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const { protocol, hostname } = new URL(url);
    return protocol === "http:" || protocol === "https:" ? hostname : null;
  } catch {
    return null;
  }
}

export function isOldDocument(
  issueDate: string | null | undefined,
  now: Date = new Date(),
): boolean {
  if (!issueDate) return false;
  const limit = new Date(now);
  limit.setFullYear(limit.getFullYear() - OLD_DOCUMENT_YEARS);
  return new Date(`${issueDate}T00:00:00Z`) < limit;
}
