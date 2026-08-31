import Link from "next/link";
import { getArticleIndex } from "@/lib/articleService";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const { articles } = await getArticleIndex();

  return (
    <main className="mx-auto w-full max-w-2xl px-6 py-12">
      <h1 className="text-2xl font-bold tracking-tight">Latest Articles</h1>

      <ul className="mt-8 space-y-8">
        {articles.map((article) => (
          <li key={article.path}>
            <Link href={`/articles/${article.path}`} className="group block">
              <h2 className="text-lg font-semibold group-hover:underline">
                {article.headline}
              </h2>
              <p className="mt-1 text-zinc-600 dark:text-zinc-400">
                {article.summary}
              </p>
              <p className="mt-1 text-sm text-zinc-500">By {article.author}</p>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
