import type { Metadata } from "next";

import { SessionView } from "@/components/SessionView";

export const metadata: Metadata = { title: "Session · VaaniOS" };

export default async function SessionPage({ params }: PageProps<"/sessions/[id]">) {
  const { id } = await params;
  return <SessionView id={id} />;
}
