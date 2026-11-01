import type { Metadata } from "next";
import {
  Mukta,
  Tiro_Devanagari_Hindi,
  Tiro_Devanagari_Marathi,
} from "next/font/google";
import Link from "next/link";
import "./globals.css";

const mukta = Mukta({
  variable: "--font-mukta",
  subsets: ["latin", "devanagari"],
  weight: ["400", "500", "600", "700"],
});

const tiroHindi = Tiro_Devanagari_Hindi({
  variable: "--font-tiro-hindi",
  subsets: ["latin", "devanagari"],
  weight: "400",
});

const tiroMarathi = Tiro_Devanagari_Marathi({
  variable: "--font-tiro-marathi",
  subsets: ["latin", "devanagari"],
  weight: "400",
  preload: false,
});

export const metadata: Metadata = {
  title: "Haq",
  description:
    "Government documents explained in your language, with every sentence linked to its source clause.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${mukta.variable} ${tiroHindi.variable} ${tiroMarathi.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <header className="border-b border-line">
          <div className="mx-auto w-full max-w-7xl px-4 py-2">
            <Link
              href="/"
              className="inline-flex min-h-11 items-baseline gap-2 text-accent focus-visible:outline-2 focus-visible:outline-accent"
            >
              <span lang="hi" className="font-display text-3xl">
                हक़
              </span>
              <span className="font-semibold">Haq</span>
            </Link>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 lg:py-12">
          {children}
        </main>
        <footer className="border-t border-line">
          <p className="mx-auto w-full max-w-7xl px-4 py-4 text-sm text-muted">
            Haq explains documents and doesn&apos;t give legal advice. Your
            answers aren&apos;t saved, and voice recordings are never kept.
          </p>
        </footer>
      </body>
    </html>
  );
}
