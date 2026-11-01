import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { AppBar, AppFooter } from "@/components/AppChrome";

export default function NotFound() {
  return (
    <>
      <AppBar />
      <main className="mx-auto flex w-full max-w-xl flex-1 flex-col items-start justify-center gap-4 px-4 py-16">
        <h1 className="text-3xl font-bold">We couldn&apos;t find that page</h1>
        <p className="text-muted">The link may be wrong, or the page may have moved.</p>
        <Link href="/" className="btn btn-primary">
          <ArrowLeft aria-hidden className="size-5" />
          Back to home
        </Link>
      </main>
      <AppFooter />
    </>
  );
}
