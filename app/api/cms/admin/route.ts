import { NextRequest, NextResponse } from "next/server";

const CMS_URL =
  process.env.CMS_URL ?? "http://localhost:8001";

/** Proxies correction publishing to the upstream CMS so the in-page toolbar
 * (and the curl command in the README) keep working from the app's origin. */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const response = await fetch(
    `${CMS_URL}/admin?${request.nextUrl.searchParams.toString()}`,
    { method: "POST" },
  );

  return NextResponse.json(await response.json(), {
    status: response.status,
  });
}
