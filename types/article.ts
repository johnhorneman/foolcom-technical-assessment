export interface ArticleData {
  path: string;
  headline: string;
  summary: string;
  author: string;
  publishedAt: string;
  updatedAt: string;
  version: number;
  body: string[];
}

export interface ArticleIndexData {
  articles: Pick<ArticleData, "path" | "headline" | "summary" | "author">[];
}
