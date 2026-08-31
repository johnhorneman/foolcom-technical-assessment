import { ArticleData, ArticleIndexData } from "@/types/article";

const CONTENT_SERVICE_URL =
  process.env.CONTENT_SERVICE_URL ?? "http://localhost:8000";

export async function getArticle(
  path: string,
  source?: string,
): Promise<ArticleData> {
  const url = new URL(`${CONTENT_SERVICE_URL}/articles/${path}`);
  if (source) url.searchParams.set("source", source);

  const response = await fetch(url, { cache: "no-store" });
  return response.json();
}

export async function getArticleIndex(): Promise<ArticleIndexData> {
  const response = await fetch(`${CONTENT_SERVICE_URL}/articles`, {
    cache: "no-store",
  });
  return response.json();
}
