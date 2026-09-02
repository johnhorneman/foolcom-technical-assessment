# Fool.com Technical Assessment

> **Submission notes for reviewers:** see [REVIEWERS.md](REVIEWERS.md) for how this was built, how to run it, and a step-by-step walkthrough of the checks below.

Article pages on [Fool.com](https://www.fool.com) serve millions of hits a month. They must stay fast and render accurate content even when an upstream service is slow, down, or hanging.

This assessment is a small, self-contained slice of that problem. Work the way you normally would, and feel free to use AI tools (Cursor, Claude Code, etc.). We use them daily ourselves.

## Your Task

This repo comes with two of its three parts: a Next.js app that renders article pages, and a mock CMS that serves article content. Your task is to build the third: a content service that sits in between.

```
Next.js → content service → mock CMS
```

1. Write a Python HTTP service that listens on port 8000. Use any framework and libraries you like. Your service gets its article data from the mock CMS at `localhost:8001` (API docs at `localhost:8001/docs`). The Next.js app is already written to call your service at two endpoints, `GET /articles` and `GET /articles/<path>`; the JSON it expects back is defined in `types/article.ts`.
2. Add a caching layer to your service. What it stores and how it's designed are your call; we want to see your cache design from scratch. If your design calls for Redis or similar, use an in-memory version rather than spinning up real infrastructure. (`?source=` is test tooling, not part of an article's identity, so don't factor it into your cache key.)
3. Make the page stay fast and keep serving article content under every [failure mode](#failure-modes): `slow`, `down`, `hang`, and `corrupt`.
4. [Publish a correction](#publishing-a-correction) to an article, then repeat step 3. The corrected version is what readers and crawlers should get, not the old copy and not an error.
5. Add observability. No real Datadog/APM integration needed, but from your service's logs or metrics alone, someone operating it should be able to answer:
   - Is the upstream healthy, slow, or failing right now?
   - Was this page served from cache or fetched fresh?
   - Did a correction propagate, and when?

   Be ready to discuss how you'd handle this in production with Datadog: what you'd measure, what you'd alert on, and what you'd leave out.

Ground rules:

- No need to deploy; everything runs locally.
- Don't use any real infrastructure.
- Don't modify anything in `services/mock_cms/`.

## Failure Modes

The CMS mocks upstream failures on demand via a `?source=<mode>` query param on any article page URL:

```bash
curl "localhost:3000/articles/<path>?source=hang"
```

| Mode      | Behavior                                                                                                         |
| --------- | ---------------------------------------------------------------------------------------------------------------- |
| (none)    | Responds normally                                                                                                |
| `slow`    | Responds successfully, after several seconds                                                                     |
| `down`    | Returns 500 errors                                                                                               |
| `hang`    | Never responds                                                                                                   |
| `corrupt` | Returns structurally-valid JSON that isn't a real article. Deciding how to validate article content is your call |

The Next.js app forwards the `source` param with the API calls to your service; your service should forward it along to the CMS so the failure modes work end to end.

## Publishing a Correction

The CMS also lets you publish a correction to an article. This mutates its content, bumping the article's `version` and `updatedAt`:

```bash
curl -X POST "localhost:3000/api/cms/admin?publish-correction=<path>"
```

## What's Given

- **The Next.js app** (repo root): an App Router app written in TypeScript. Article pages are served through a catch-all route at `/articles/[...slug]`, e.g. `/articles/investing/2026/07/23/invest-10000-nvidia-stock-10-years-ago-how-much`. Like the real Fool.com, the page is a dynamic async server component that fetches article content from the content service on every request (see `lib/articleService.ts`).
- **The mock CMS** (`services/mock_cms/`, port 8001): the CMS API that serves article content. It can reproduce upstream failures on demand, and its API is browsable at `localhost:8001/docs`. Treat it like a remote service you don't own.

## How We'll Check It

Load each article and failure mode (`?source=hang`, `down`, `slow`, `corrupt`) and
confirm a fast response with accurate article content. Then
[publish a correction](#publishing-a-correction) and do the same again: every
response should now be the corrected version, still fast under every failure mode.
We'll also read your code, and we'll walk through your design decisions
together in a follow-up conversation.

## Getting Started

Requirements: Node 20+, and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
npm install
npm run dev   # starts the Next.js app and the mock CMS
```

Run your content service however you like.

Open [http://localhost:3000](http://localhost:3000). The home page links to the seeded articles, and each article page has a toolbar for switching failure modes and publishing corrections. The pages will error until your service is up.

Note: the mock CMS stores articles in memory, so corrections reset when the servers restart.

## Submitting

Push your work to a public repo (or zip the repo) and send it back to us. We'll walk through your decisions together in a follow-up conversation.
