import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/constants";
import {
  API_URL,
  applyAuthCookies,
  clearAuthCookies,
  isCrossSiteWrite,
  refreshOnce,
  type TokenPair,
} from "@/lib/server";

const FORWARDED_REQUEST_HEADERS = ["content-type", "accept", "x-organisation-id"];
const FORWARDED_RESPONSE_HEADERS = ["content-type", "content-disposition"];

type Context = { params: Promise<{ path: string[] }> };

function unauthorized() {
  const res = NextResponse.json({ detail: "Authentification requise" }, { status: 401 });
  clearAuthCookies(res);
  return res;
}

async function handler(req: NextRequest, ctx: Context) {
  const { path } = await ctx.params;

  // Pas de ".." ni de séparateur caché : on ne sort pas du chemin demandé.
  if (path.some((s) => s === ".." || s === "." || s.includes("\\") || s.includes("/"))) {
    return NextResponse.json({ detail: "Chemin invalide" }, { status: 400 });
  }
  const joined = path.join("/");
  // Connexion, rafraîchissement et déconnexion passent par /api/auth/* (cookies httpOnly).
  if (joined.startsWith("auth/") && joined !== "auth/me") {
    return NextResponse.json({ detail: "Introuvable" }, { status: 404 });
  }
  if (isCrossSiteWrite(req)) return NextResponse.json({ detail: "Origine refusée" }, { status: 403 });

  const store = await cookies();
  let access = store.get(ACCESS_COOKIE)?.value;
  const refresh = store.get(REFRESH_COOKIE)?.value;
  const userAgent = req.headers.get("user-agent") ?? "";
  let renewed: TokenPair | null = null;

  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  const body = hasBody ? await req.arrayBuffer() : undefined;
  const target = `${API_URL}/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  const send = (token: string) => {
    const headers = new Headers();
    for (const name of FORWARDED_REQUEST_HEADERS) {
      const value = req.headers.get(name);
      if (value) headers.set(name, value);
    }
    headers.set("authorization", `Bearer ${token}`);
    return fetch(target, {
      method: req.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(30_000),
    });
  };

  if (!access && refresh) {
    renewed = await refreshOnce(refresh, userAgent);
    access = renewed?.access_token;
  }
  if (!access) return unauthorized();

  let upstream: Response;
  try {
    upstream = await send(access);
    if (upstream.status === 401 && refresh && !renewed) {
      renewed = await refreshOnce(refresh, userAgent);
      if (!renewed) return unauthorized();
      upstream = await send(renewed.access_token);
    }
  } catch {
    return NextResponse.json({ detail: "Serveur indisponible, réessaie dans un instant." }, { status: 502 });
  }

  const noBody = upstream.status === 204 || upstream.status === 304;
  const res = new NextResponse(noBody ? null : await upstream.arrayBuffer(), { status: upstream.status });
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) res.headers.set(name, value);
  }
  res.headers.set("cache-control", "no-store");
  if (renewed) applyAuthCookies(res, renewed);
  return res;
}

export { handler as GET, handler as POST, handler as PATCH, handler as PUT, handler as DELETE };
