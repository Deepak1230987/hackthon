import { SourceInput } from "@/components/SourceInput";

export default function Home() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-8">
      <div>
        <p lang="hi" className="mb-2 text-lg font-medium text-accent">
          अपना हक़ जानिए
        </p>
        <h1 className="text-3xl leading-tight font-semibold text-balance">
          Find out what a government document means for you
        </h1>
        <p className="mt-3 text-muted">
          Hear it explained in your language, with every sentence linked to the
          clause it came from.
        </p>
      </div>
      <SourceInput />
    </div>
  );
}
