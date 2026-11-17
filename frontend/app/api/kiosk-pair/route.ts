import { NextRequest, NextResponse } from "next/server";
import { TERMINAL_COOKIE } from "@/lib/constants";
import { API_URL, isCrossSiteWrite } from "@/lib/server";

const cookieOptions = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
};

async function fetchInfo(key: string): Promise<Response> {
  return fetch(`${API_URL}/kiosk/me`, { headers: { "x-terminal-key": key }, cache: "no-store" });
}

/** Terminal déjà appairé ? Renvoie ses informations si oui. */
export async function GET(req: NextRequest) {
  const key = req.cookies.get(TERMINAL_COOKIE)?.value;
  if (!key) return NextResponse.json({ detail: "Terminal non appairé" }, { status: 401 });
  try {
    const upstream = await fetchInfo(key);
    const res = NextResponse.json(await upstream.json().catch(() => ({})), { status: upstream.status });
    if (upstream.status === 401) res.cookies.set(TERMINAL_COOKIE, "", { ...cookieOptions, maxAge: 0 });
    return res;
  } catch {
    return NextResponse.json({ detail: "Serveur indisponible" }, { status: 502 });
  }
}

/** Appaire ce poste : la clé est vérifiée puis gardée dans un cookie httpOnly (le navigateur ne la relit jamais). */
export async function POST(req: NextRequest) {
  if (isCrossSiteWrite(req)) return NextResponse.json({ detail: "Origine refusée" }, { status: 403 });
  let key = "";
  try {
    key = String((await req.json()).key ?? "").trim();
  } catch {
    return NextResponse.json({ detail: "Requête invalide" }, { status: 400 });
  }
  if (!key) return NextResponse.json({ detail: "Colle la clé du terminal" }, { status: 400 });
  try {
    const upstream = await fetchInfo(key);
    const body = await upstream.json().catch(() => ({}));
    if (!upstream.ok) return NextResponse.json({ detail: "Clé de terminal invalide ou désactivée" }, { status: 401 });
    const res = NextResponse.json(body);
    res.cookies.set(TERMINAL_COOKIE, key, { ...cookieOptions, maxAge: 60 * 60 * 24 * 365 });
    return res;
  } catch {
    return NextResponse.json({ detail: "Serveur indisponible" }, { status: 502 });
  }
}

export async function DELETE(req: NextRequest) {
  if (isCrossSiteWrite(req)) return NextResponse.json({ detail: "Origine refusée" }, { status: 403 });
  const res = new NextResponse(null, { status: 204 });
  res.cookies.set(TERMINAL_COOKIE, "", { ...cookieOptions, maxAge: 0 });
  return res;
}
