import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { TERMINAL_COOKIE } from "@/lib/constants";
import { API_URL, isCrossSiteWrite } from "@/lib/server";

type Context = { params: Promise<{ path: string[] }> };

/** Relaie les appels du terminal vers l'API en ajoutant sa clé (gardée dans un cookie httpOnly). */
async function handler(req: NextRequest, ctx: Context) {
  const { path } = await ctx.params;
  if (path.some((s) => s === ".." || s === "." || s.includes("\\") || s.includes("/"))) {
    return NextResponse.json({ detail: "Chemin invalide" }, { status: 400 });
  }
  if (isCrossSiteWrite(req)) return NextResponse.json({ detail: "Origine refusée" }, { status: 403 });

  const key = (await cookies()).get(TERMINAL_COOKIE)?.value;
  if (!key) return NextResponse.json({ detail: "Terminal non appairé" }, { status: 401 });

  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  const headers = new Headers({ "x-terminal-key": key });
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);

  try {
    const upstream = await fetch(`${API_URL}/kiosk/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`, {
      method: req.method,
      headers,
      body: hasBody ? await req.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(60_000), // l'analyse d'une séquence d'images prend quelques secondes
    });
    const res = new NextResponse(upstream.status === 204 ? null : await upstream.arrayBuffer(), { status: upstream.status });
    for (const name of ["content-type", "retry-after"]) {
      const value = upstream.headers.get(name);
      if (value) res.headers.set(name, value);
    }
    res.headers.set("cache-control", "no-store");
    return res;
  } catch {
    return NextResponse.json({ detail: "Serveur indisponible, réessayez dans un instant." }, { status: 502 });
  }
}

export { handler as GET, handler as POST };
