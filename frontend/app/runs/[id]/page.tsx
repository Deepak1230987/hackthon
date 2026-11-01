import { Suspense } from "react";

import { AppBar } from "@/components/AppChrome";
import { Spinner } from "@/components/ui";

import { RunScreen } from "./RunScreen";

type Params = Promise<{ id: string }>;

async function Run({ params }: { params: Params }) {
  const { id } = await params;
  return <RunScreen key={id} id={id} />;
}

export default function RunPage({ params }: { params: Params }) {
  return (
    <Suspense
      fallback={
        <>
          <AppBar />
          <h1 className="flex items-center gap-3 p-8 text-xl font-semibold">
            <Spinner />
            Loading your document…
          </h1>
        </>
      }
    >
      <Run params={params} />
    </Suspense>
  );
}
