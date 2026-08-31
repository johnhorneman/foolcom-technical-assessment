"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import React, { useState } from "react";

const MODES = ["healthy", "slow", "down", "hang", "corrupt"] as const;

export function MockSourcesToolbar(): React.ReactNode {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const [publishing, setPublishing] = useState(false);

  if (!pathname.startsWith("/articles/")) {
    return null;
  }

  const articlePath = pathname.replace(/^\/articles\//, "");
  const activeMode = searchParams.get("source") ?? "healthy";

  const publishCorrection = async (): Promise<void> => {
    setPublishing(true);
    try {
      await fetch(
        `/api/cms/admin?publish-correction=${encodeURIComponent(articlePath)}`,
        { method: "POST" },
      );
      router.refresh();
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div className="fixed bottom-10 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-full border border-zinc-600 bg-zinc-900/95 px-3 py-1.5 font-mono text-[13px] text-zinc-300 shadow-2xl ring-1 ring-black/40 backdrop-blur">
      {MODES.map((mode) => (
        <Link
          key={mode}
          href={mode === "healthy" ? pathname : `${pathname}?source=${mode}`}
          prefetch={false}
          className={
            mode === activeMode
              ? "rounded-full bg-emerald-400 px-2.5 py-0.5 font-bold text-zinc-950"
              : "rounded-full px-2.5 py-0.5 hover:bg-zinc-700 hover:text-white"
          }
        >
          {mode}
        </Link>
      ))}

      <span className="mx-1.5 h-4 w-px select-none bg-zinc-600" />

      <button
        type="button"
        onClick={publishCorrection}
        disabled={publishing}
        className="cursor-pointer rounded-full border border-amber-400/60 px-2.5 py-0.5 font-semibold text-amber-300 hover:bg-amber-400 hover:text-zinc-950 disabled:opacity-50"
      >
        {publishing ? "publishing..." : "publish correction"}
      </button>
    </div>
  );
}
