"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="mx-auto w-full max-w-2xl px-6 py-12">
      <h1 className="text-2xl font-bold tracking-tight">
        This page failed to render
      </h1>
      <p className="mt-4 text-zinc-600 dark:text-zinc-400">
        If you haven&apos;t built the content service yet, this is expected:
        the app fetches article data from{" "}
        <code className="rounded bg-zinc-100 px-1 font-mono text-sm dark:bg-zinc-800">
          localhost:8000
        </code>
        , which isn&apos;t responding. See the README for what to build.
      </p>
      <p className="mt-2 text-sm text-zinc-500">{error.message}</p>
      <button
        type="button"
        onClick={reset}
        className="mt-6 cursor-pointer rounded-md border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
      >
        Try again
      </button>
    </main>
  );
}
