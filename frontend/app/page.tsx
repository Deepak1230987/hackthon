import {
  Calculator,
  Check,
  FileSearch,
  Headphones,
  MessageCircleQuestion,
  ScanSearch,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

import { AppFooter, Brand } from "@/components/AppChrome";
import { RunHistory } from "@/components/RunHistory";
import { SourceInput } from "@/components/SourceInput";

const HIGHLIGHTS = [
  "Listen in Hindi or Marathi",
  "Every sentence linked to its clause",
  "Answers checked against the document",
];

const STEPS: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: FileSearch,
    title: "Give us the document",
    text: "Upload a PDF, paste a link, or choose one from the library.",
  },
  {
    icon: Headphones,
    title: "Listen in your language",
    text: "Hear what it means for you, and follow along with the words on screen.",
  },
  {
    icon: MessageCircleQuestion,
    title: "See if it applies, and ask",
    text: "Answer a few questions to check if you qualify, then ask anything else.",
  },
];

const PROMISES: { icon: LucideIcon; text: string }[] = [
  {
    icon: ScanSearch,
    text: "Each point is checked against the clause it came from. If it doesn't match, it's corrected or left out.",
  },
  {
    icon: Calculator,
    text: "Whether you qualify is calculated by code from the document's stated rules, not guessed by AI.",
  },
  {
    icon: ShieldCheck,
    text: "If the document doesn't say, Haq tells you so.",
  },
];

// A worked example, so "linked to its clause" means something before the first upload.
function SourceLinkExample() {
  return (
    <figure className="card overflow-hidden">
      <figcaption className="border-b border-line bg-sunken/60 px-4 py-2 text-sm font-medium text-muted">
        Example, for illustration
      </figcaption>
      <div className="p-4 sm:p-6">
        <p className="eyebrow">What you hear</p>
        <p lang="hi" className="mt-1 text-xl leading-relaxed font-medium">
          60 साल की उम्र के बाद आपको हर महीने ₹3,000 की पेंशन मिलती है।
        </p>
        <p className="mt-1 text-sm text-muted">
          After you turn 60, you get a pension of ₹3,000 every month.
        </p>
        <div aria-hidden className="my-3 ml-4 h-8 w-0.5 bg-highlight-strong" />
        <p className="text-sm font-semibold text-highlight-strong">
          Where it comes from: page 1
        </p>
        <div className="mt-2 rounded-lg border border-line bg-paper p-3 font-display leading-relaxed sm:p-4">
          <p className="text-muted">Operational guidelines</p>
          <p className="mt-2">
            1. The scheme provides{" "}
            <mark className="rounded-sm bg-highlight/70 px-0.5 text-ink">
              an assured monthly pension of Rs. 3000
            </mark>{" "}
            to eligible subscribers on attaining the age of 60 years.
          </p>
        </div>
      </div>
    </figure>
  );
}

export default function Home() {
  return (
    <>
      <div className="guilloche on-night text-white">
        <header className="mx-auto w-full max-w-6xl px-4 pt-3 lg:px-8">
          <Brand tone="night" />
        </header>
        <div className="mx-auto w-full max-w-6xl px-4 pt-5 pb-24 lg:min-h-[34rem] lg:px-8 lg:pt-14 lg:pb-16">
          <div className="lg:w-[46%]">
            <p
              lang="hi"
              className="font-display text-5xl leading-[1.25] sm:text-6xl xl:text-7xl"
            >
              अपना <span className="marker rounded-md px-2">हक़</span> जानिए
            </p>
            <h1 className="mt-4 text-2xl leading-snug font-bold text-balance lg:mt-6 lg:text-3xl">
              Find out what a government document means for you
            </h1>
            <ul className="mt-6 hidden flex-col gap-2.5 lg:flex">
              {HIGHLIGHTS.map((line) => (
                <li key={line} className="flex items-center gap-2.5 text-lg text-white/90">
                  <Check aria-hidden className="size-5 shrink-0 text-highlight" />
                  {line}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <main className="flex-1">
        <div className="mx-auto w-full max-w-6xl px-4 lg:px-8">
          {/* On a wide screen the form rises into the hero, beside the headline. It stays
              in the flow, so a longer library list pushes the page down, not over it. */}
          <div className="relative z-10 -mt-20 lg:-mt-[32rem] lg:ml-auto lg:w-[48%]">
            <div className="card p-4 shadow-float sm:p-6">
              <SourceInput />
            </div>
          </div>

          <div className="flex flex-col gap-14 py-10 lg:gap-20 lg:py-16">
            <RunHistory />

            <section
              aria-labelledby="how-heading"
              className="grid items-start gap-8 lg:grid-cols-2 lg:gap-14"
            >
              <div>
                <h2 id="how-heading" className="text-2xl font-bold lg:text-3xl">
                  How Haq works
                </h2>
                <ol className="mt-6 flex flex-col gap-6">
                  {STEPS.map(({ icon: Icon, title, text }) => (
                    <li key={title} className="flex gap-4">
                      <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent">
                        <Icon aria-hidden className="size-5" />
                      </span>
                      <div>
                        <h3 className="text-lg font-semibold">{title}</h3>
                        <p className="text-muted">{text}</p>
                      </div>
                    </li>
                  ))}
                </ol>
              </div>
              <SourceLinkExample />
            </section>

            <section aria-labelledby="trust-heading">
              <h2 id="trust-heading" className="text-2xl font-bold lg:text-3xl">
                Why you can check what it says
              </h2>
              <ul className="mt-6 grid gap-4 md:grid-cols-3">
                {PROMISES.map(({ icon: Icon, text }) => (
                  <li key={text} className="card p-5">
                    <Icon aria-hidden className="size-6 text-accent" />
                    <p className="mt-3">{text}</p>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </div>
      </main>
      <AppFooter />
    </>
  );
}
