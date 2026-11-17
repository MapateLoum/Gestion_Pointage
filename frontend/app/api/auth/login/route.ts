import { NextRequest, NextResponse } from "next/server";
import { API_URL, applyAuthCookies, isCrossSiteWrite, type TokenPair } from "@/lib/server";

export async function POST(req: NextRequest) {
  if (isCrossSiteWrite(req)) return NextResponse.json({ detail: "Origine refusée" }, { status: 403 });

  let payload: { email?: string; password?: string };
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ detail: "Requête invalide" }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json", "user-agent": req.headers.get("user-agent") ?? "" },
      body: JSON.stringify({ email: payload.email, password: payload.password }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "Serveur indisponible, réessaie dans un instant." }, { status: 502 });
  }

  if (!upstream.ok) {
    const body = await upstream.json().catch(() => ({ detail: "Connexion impossible" }));
    return NextResponse.json(body, { status: upstream.status });
  }

  const tokens = (await upstream.json()) as TokenPair;
  const me = await fetch(`${API_URL}/auth/me`, {
    headers: { authorization: `Bearer ${tokens.access_token}` },
    cache: "no-store",
  });
  const res = NextResponse.json(await me.json());
  applyAuthCookies(res, tokens); // les jetons restent dans des cookies httpOnly
  return res;
}
