"use client";

import { useEffect } from "react";

import { ErrorState } from "@/components/ui";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="stack">
      <ErrorState title="Page unavailable" message={error.message || "An unexpected error occurred."} />
      <button className="button button-secondary" onClick={reset} type="button">
        Retry
      </button>
    </div>
  );
}
