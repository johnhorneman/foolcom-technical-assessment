import type { Metadata } from "next";

import { getArticle } from "@/lib/articleService";

export const dynamic = "force-dynamic";

type PageProps = {
  params: Promise<{ slug: string[] }>;
  searchParams: Promise<{ source?: string }>;
};

const formatDate = (iso: string): string =>
  new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });

export async function generateMetadata({
  params,
  searchParams,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const { source } = await searchParams;

  const article = await getArticle(slug.join("/"), source);

  return {
    title: `${article.headline} | The Motley Fool`,
    description: article.summary,
  };
}

export default async function ArticlePage({ params, searchParams }: PageProps) {
  const { slug } = await params;
  const { source } = await searchParams;

  const article = await getArticle(slug.join("/"), source);

  return (
    <article className="mx-auto w-full max-w-2xl px-6 py-12">
      <h1 className="text-3xl font-bold leading-tight tracking-tight">
        {article.headline}
      </h1>

      <p className="mt-3 text-lg text-zinc-600 dark:text-zinc-400">
        {article.summary}
      </p>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 py-3">
        <p className="text-sm text-zinc-500">
          By{" "}
          <span className="font-medium text-zinc-800 dark:text-zinc-200">
            {article.author}
          </span>
          <span className="mx-2 text-zinc-300 dark:text-zinc-700">|</span>
          {formatDate(article.publishedAt)}
        </p>
        <p className="flex items-center text-xs text-zinc-500">
          <span
            data-testid="article-version"
            title={`Updated ${article.updatedAt}`}
            className="rounded-full bg-zinc-100 px-2 py-0.5 font-mono font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
          >
            v{article.version}
          </span>
        </p>
      </div>

      <div className="mt-6 space-y-5 text-base leading-7">
        {article.body.map((paragraph, index) => (
          <p key={index}>{paragraph}</p>
        ))}
      </div>
    </article>
  );
}
