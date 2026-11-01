import type { Metadata, Viewport } from "next";
import {
  Mukta,
  Tiro_Devanagari_Hindi,
  Tiro_Devanagari_Marathi,
} from "next/font/google";
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

// Lets the bottom navigation sit clear of a phone's home bar.
export const viewport: Viewport = {
  viewportFit: "cover",
  themeColor: "#17103f",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${mukta.variable} ${tiroHindi.variable} ${tiroMarathi.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
