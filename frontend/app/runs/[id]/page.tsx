import { Suspense } from "react";

import { RunScreen } from "./RunScreen";

type Params = Promise<{ id: string }>;

async function Run({ params }: { params: Params }) {
  const { id } = await params;
  return <RunScreen key={id} id={id} />;
}

export default function RunPage({ params }: { params: Params }) {
  return (
    <Suspense
      fallback={<h1 className="text-2xl font-semibold">Loading your run…</h1>}
    >
      <Run params={params} />
    </Suspense>
  );
}
