import type { Metadata } from "next";
import { Noto_Sans, Noto_Sans_Devanagari } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const notoSans = Noto_Sans({
  variable: "--font-noto-sans",
  subsets: ["latin"],
});

const notoDevanagari = Noto_Sans_Devanagari({
  variable: "--font-noto-devanagari",
  subsets: ["devanagari"],
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
      className={`${notoSans.variable} ${notoDevanagari.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <header className="border-b border-line">
          <div className="mx-auto w-full max-w-7xl px-4 py-3">
            <Link href="/" className="text-xl font-bold text-accent">
              Haq
            </Link>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8">
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
