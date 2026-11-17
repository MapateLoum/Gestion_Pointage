"use client";

import { useSession } from "@/components/session";
import { api } from "./api";
import { useQuery } from "./hooks";
import type { Department, Group, Site } from "./types";

/** Sites, départements et groupes de l'organisation active (listes de référence). */
export function useStructure(enabled = true) {
  const { orgId, needsOrg } = useSession();
  const k = enabled && !needsOrg ? orgId ?? "me" : null;
  const sites = useQuery(k && `sites|${k}`, () => api<Site[]>("sites", { query: { limit: 500 } }));
  const departments = useQuery(k && `departments|${k}`, () => api<Department[]>("departments", { query: { limit: 500 } }));
  const groups = useQuery(k && `groups|${k}`, () => api<Group[]>("groups", { query: { limit: 500 } }));
  return {
    sites,
    departments,
    groups,
    loading: sites.loading || departments.loading || groups.loading,
    reloadAll: () => {
      sites.reload();
      departments.reload();
      groups.reload();
    },
  };
}
