import { RunHistory } from "@/components/RunHistory";
import { SourceInput } from "@/components/SourceInput";

const PROMISES = [
  "Each point is checked against the clause it came from. If it doesn't match, it's corrected or left out.",
  "Whether you qualify is calculated by code from the document's stated rules, not guessed by AI.",
  "If the document doesn't say, Haq tells you so.",
];

export default function Home() {
  return (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:gap-16">
      <div className="lg:sticky lg:top-12 lg:self-start">
        <p
          lang="hi"
          className="font-display text-5xl leading-tight text-accent-strong sm:text-6xl xl:text-7xl"
        >
          <span className="marker">अपना हक़ जानिए</span>
        </p>
        <h1 className="mt-6 text-2xl leading-snug font-semibold text-balance">
          Find out what a government document means for you
        </h1>
        <p className="mt-3 text-lg text-muted">
          Hear it explained in your language, with every sentence linked to the
          clause it came from.
        </p>
        <ul className="mt-6 hidden flex-col gap-3 lg:flex">
          {PROMISES.map((promise) => (
            <li key={promise} className="border-l-4 border-accent-soft pl-3">
              {promise}
            </li>
          ))}
        </ul>
      </div>
      <div className="flex min-w-0 flex-col gap-8">
        <div className="rounded-xl border border-line bg-surface p-4 sm:p-6">
          <SourceInput />
        </div>
        <RunHistory />
      </div>
    </div>
  );
}
