"use client";

import { Fingerprint, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setStoredOrgId, getStoredOrgId } from "@/lib/api";
import type { Organisation, User } from "@/lib/types";
import { Button } from "./ui";

interface Session {
  me: User;
  /** Organisation active : celle de l'utilisateur, ou celle choisie par un super_admin. */
  orgId: string | null;
  currentOrg: Organisation | null;
  organisations: Organisation[];
  /** Vrai pour un super_admin qui n'a pas encore choisi d'organisation. */
  needsOrg: boolean;
  setOrgId: (id: string | null) => void;
  reloadOrganisations: () => void;
  logout: () => Promise<void>;
}

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<User | null>(null);
  const [organisations, setOrganisations] = useState<Organisation[]>([]);
  const [orgId, setOrgIdState] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const user = await api<User>("auth/me");
        if (cancelled) return;
        if (user.role === "super_admin") {
          const list = await api<Organisation[]>("organisations", { query: { limit: 200 } });
          if (cancelled) return;
          setOrganisations(list);
          const stored = getStoredOrgId();
          const valid = stored && list.some((o) => o.id === stored) ? stored : null;
          setStoredOrgId(valid);
          setOrgIdState(valid);
        } else {
          setStoredOrgId(null); // un compte non super_admin n'envoie jamais d'en-tête d'organisation
          setOrgIdState(user.organisation_id);
        }
        setMe(user);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Erreur");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tick]);

  const setOrgId = useCallback((id: string | null) => {
    setStoredOrgId(id);
    setOrgIdState(id);
  }, []);

  const logout = useCallback(async () => {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    setStoredOrgId(null);
    router.replace("/login");
  }, [router]);

  const value = useMemo<Session | null>(() => {
    if (!me) return null;
    return {
      me,
      orgId,
      currentOrg: organisations.find((o) => o.id === orgId) ?? null,
      organisations,
      needsOrg: me.role === "super_admin" && !orgId,
      setOrgId,
      reloadOrganisations: () => setTick((t) => t + 1),
      logout,
    };
  }, [me, orgId, organisations, setOrgId, logout]);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-6 text-center">
        <p className="text-sm text-muted-foreground">{error}</p>
        <div className="flex gap-2">
          <Button onClick={() => setTick((t) => t + 1)}>Réessayer</Button>
          <Button variant="outline" onClick={() => (window.location.href = "/login")}>
            Retour à la connexion
          </Button>
        </div>
      </div>
    );
  }
  if (!value) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-muted-foreground">
        <Fingerprint className="h-10 w-10 animate-pulse text-primary" aria-hidden />
        <span className="flex items-center gap-2 text-sm">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Chargement…
        </span>
      </div>
    );
  }
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession doit être utilisé dans <SessionProvider>");
  return ctx;
}
