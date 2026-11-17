import { NextResponse } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "./constants";

export const API_URL = process.env.API_URL ?? "http://localhost:8000";
const REFRESH_MAX_AGE = 7 * 24 * 3600; // aligné sur REFRESH_TOKEN_DAYS côté API

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

const cookieBase = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
};

export function applyAuthCookies(res: NextResponse, tokens: TokenPair) {
  res.cookies.set(ACCESS_COOKIE, tokens.access_token, { ...cookieBase, maxAge: tokens.expires_in });
  res.cookies.set(REFRESH_COOKIE, tokens.refresh_token, { ...cookieBase, maxAge: REFRESH_MAX_AGE });
}

export function clearAuthCookies(res: NextResponse) {
  res.cookies.set(ACCESS_COOKIE, "", { ...cookieBase, maxAge: 0 });
  res.cookies.set(REFRESH_COOKIE, "", { ...cookieBase, maxAge: 0 });
}

/**
 * Plusieurs requêtes du navigateur peuvent arriver en même temps avec le même jeton
 * de rafraîchissement expiré. L'API utilise la rotation (un jeton ne sert qu'une fois,
 * sa réutilisation coupe toutes les sessions) : on ne doit donc faire UN SEUL appel
 * /auth/refresh et partager son résultat entre toutes les requêtes simultanées.
 */
const inflight = new Map<string, { promise: Promise<TokenPair | null>; at: number }>();

export function refreshOnce(refreshToken: string, userAgent = ""): Promise<TokenPair | null> {
  const now = Date.now();
  for (const [key, entry] of inflight) if (now - entry.at > 30_000) inflight.delete(key);

  const existing = inflight.get(refreshToken);
  if (existing) return existing.promise;

  const promise = (async () => {
    try {
      const response = await fetch(`${API_URL}/auth/refresh`, {
        method: "POST",
        headers: { "content-type": "application/json", "user-agent": userAgent },
        body: JSON.stringify({ refresh_token: refreshToken }),
        cache: "no-store",
      });
      return response.ok ? ((await response.json()) as TokenPair) : null;
    } catch {
      return null;
    }
  })();
  inflight.set(refreshToken, { promise, at: now });
  return promise;
}

/** Refuse les requêtes qui modifient des données et viennent d'un autre site. */
export function isCrossSiteWrite(req: Request): boolean {
  if (req.method === "GET" || req.method === "HEAD") return false;
  const origin = req.headers.get("origin");
  if (!origin) return false;
  try {
    return new URL(origin).host !== req.headers.get("host");
  } catch {
    return true;
  }
}
