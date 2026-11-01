// What's wrong with a chosen range, or null. The backend checks it again.
export function pageRangeProblem(
  from: number,
  to: number,
  pageCount: number,
  maxPages: number,
): string | null {
  if (!Number.isInteger(from) || !Number.isInteger(to)) {
    return "Enter whole page numbers.";
  }
  if (from < 1 || to > pageCount) return `Choose pages between 1 and ${pageCount}.`;
  if (from > to) return "The first page must come before the last page.";
  if (to - from + 1 > maxPages) return `Choose ${maxPages} pages or fewer.`;
  return null;
}
