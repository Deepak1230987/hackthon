import Link from "next/link";
import type { ReactNode } from "react";

export function Brand({ tone = "day" }: { tone?: "day" | "night" }) {
  return (
    <Link
      href="/"
      aria-label="Haq home"
      className={`inline-flex min-h-11 shrink-0 items-center gap-2 rounded-md ${
        tone === "night" ? "text-white" : "text-accent-strong"
      }`}
    >
      <span lang="hi" className="font-display text-3xl leading-none">
        हक़
      </span>
      <span className="font-semibold">Haq</span>
    </Link>
  );
}

// The bar a run sits under. It stays put, so home is always one tap away.
export function AppBar({ children }: { children?: ReactNode }) {
  return (
    <header
      data-app-chrome
      className="sticky top-0 z-40 border-b border-line bg-surface"
    >
      <div className="flex h-14 items-center gap-3 px-4 lg:px-8">
        <Brand />
        {children}
      </div>
    </header>
  );
}

export function AppFooter({ className = "" }: { className?: string }) {
  return (
    <footer data-app-chrome className={`border-t border-line ${className}`}>
      <p className="mx-auto w-full max-w-6xl px-4 py-5 text-sm text-muted lg:px-8">
        Haq explains documents and doesn&apos;t give legal advice. Your answers
        aren&apos;t saved, and voice recordings are never kept.
      </p>
    </footer>
  );
}
