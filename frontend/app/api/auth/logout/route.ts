import { NextRequest, NextResponse } from "next/server";
import { REFRESH_COOKIE } from "@/lib/constants";
import { API_URL, clearAuthCookies, isCrossSiteWrite } from "@/lib/server";

export async function POST(req: NextRequest) {
  if (isCrossSiteWrite(req)) return NextResponse.json({ detail: "Origine refusée" }, { status: 403 });

  const refresh = req.cookies.get(REFRESH_COOKIE)?.value;
  if (refresh) {
    await fetch(`${API_URL}/auth/logout`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
      cache: "no-store",
    }).catch(() => undefined); // on efface les cookies même si l'API ne répond pas
  }
  const res = new NextResponse(null, { status: 204 });
  clearAuthCookies(res);
  return res;
}
