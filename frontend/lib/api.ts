import { ORG_STORAGE_KEY } from "./constants";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message);
  }
}

export const getStoredOrgId = (): string | null =>
  typeof window === "undefined" ? null : window.localStorage.getItem(ORG_STORAGE_KEY);

export function setStoredOrgId(id: string | null) {
  if (typeof window === "undefined") return;
  if (id) window.localStorage.setItem(ORG_STORAGE_KEY, id);
  else window.localStorage.removeItem(ORG_STORAGE_KEY);
}

type QueryValue = string | number | boolean | null | undefined;

interface ApiOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  form?: FormData;
  query?: Record<string, QueryValue>;
}

/** Transforme l'erreur renvoyée par FastAPI en phrase lisible. */
function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const loc = Array.isArray(item?.loc) ? item.loc.filter((p: unknown) => p !== "body").join(".") : "";
        return loc ? `${loc} : ${item?.msg ?? "invalide"}` : String(item?.msg ?? "invalide");
      })
      .join(" ; ");
  }
  if (detail && typeof detail === "object") return Object.values(detail).join(", ");
  return "Une erreur est survenue";
}

/** Appelle l'API via le proxy du front : le navigateur ne voit jamais les jetons. */
export async function api<T = unknown>(path: string, opts: ApiOptions = {}): Promise<T> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(opts.query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const url = `/api/proxy/${path}${params.size ? `?${params}` : ""}`;

  const headers: Record<string, string> = {};
  const orgId = getStoredOrgId();
  if (orgId) headers["X-Organisation-Id"] = orgId;

  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }

  let response: Response;
  try {
    response = await fetch(url, { method: opts.method ?? "GET", headers, body, cache: "no-store" });
  } catch {
    throw new ApiError(0, "Impossible de joindre le serveur. Vérifie ta connexion.");
  }

  if (response.status === 401) {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    window.location.href = "/login";
    throw new ApiError(401, "Session expirée");
  }
  if (response.status === 204) return undefined as T;

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const message =
      data && typeof data === "object" && "detail" in data
        ? formatDetail((data as { detail: unknown }).detail)
        : "Une erreur est survenue";
    throw new ApiError(response.status, message, data);
  }
  return data as T;
}
