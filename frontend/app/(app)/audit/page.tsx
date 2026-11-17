"use client";

import { ChevronLeft, ChevronRight, ScrollText } from "lucide-react";
import { useEffect, useState } from "react";
import { Page } from "@/components/page";
import { useSession } from "@/components/session";
import { Badge, Button, Card, EmptyState, ErrorNote, PageHeader, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/hooks";
import { AUDIT_ACTION_LABELS, formatDateTime } from "@/lib/labels";
import type { AuditLog, User } from "@/lib/types";

const PAGE_SIZE = 25;

function tone(action: string) {
  if (action.includes("failed") || action.includes("locked") || action.includes("blocked") || action.includes("reuse") || action.includes("regression")) return "danger" as const;
  if (action.endsWith(".deleted")) return "warning" as const;
  if (action.endsWith(".created") || action.endsWith("success") || action.endsWith("imported")) return "success" as const;
  return "neutral" as const;
}

function summary(details: Record<string, unknown>): string {
  return Object.entries(details)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`)
    .join(" · ");
}

export default function AuditPage() {
  const { me, orgId } = useSession();
  const [action, setAction] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [action, orgId]);

  const allowed = me.role === "super_admin" || me.role === "admin_organisation";
  const logs = useQuery(allowed ? JSON.stringify(["audit", orgId, action, page]) : null, () =>
    api<AuditLog[]>("audit-logs", { query: { action: action || undefined, limit: PAGE_SIZE, offset: page * PAGE_SIZE } }),
  );
  const users = useQuery(allowed ? `audit-users|${orgId ?? "all"}` : null, () => api<User[]>("users", { query: { limit: 200 } }));

  if (!allowed) return <ErrorNote message="Cette page est réservée aux administrateurs." />;

  const actor = (id: string | null) => {
    if (!id) return "Système / inconnu";
    return users.data?.find((u) => u.id === id)?.full_name ?? `Compte ${id.slice(0, 8)}`;
  };
  const rows = logs.data;

  return (
    <Page>
      <PageHeader title="Journal d'audit" description="Qui a fait quoi, et quand. Les entrées ne peuvent être ni modifiées ni supprimées." />

      <Card className="mb-4 p-3">
        <div className="max-w-sm">
          <Select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Filtrer par action">
            <option value="">Toutes les actions</option>
            {Object.entries(AUDIT_ACTION_LABELS).map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </Select>
        </div>
      </Card>

      {logs.error && <ErrorNote message={logs.error} onRetry={logs.reload} />}

      <Card className="overflow-hidden">
        {logs.loading && !rows ? (
          <div className="space-y-3 p-5">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : rows && rows.length === 0 ? (
          <EmptyState icon={ScrollText} title="Aucune entrée" description="Rien ne correspond à ce filtre pour l'instant." />
        ) : (
          rows && (
            <div className={logs.loading ? "overflow-x-auto opacity-60 transition-opacity" : "overflow-x-auto transition-opacity"}>
              <table className="w-full text-sm">
                <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-5 py-3 font-medium">Date</th>
                    <th className="px-5 py-3 font-medium">Action</th>
                    <th className="px-5 py-3 font-medium">Auteur</th>
                    <th className="px-5 py-3 font-medium">IP</th>
                    <th className="px-5 py-3 font-medium">Détails</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {rows.map((r) => (
                    <tr key={r.id} className="align-top hover:bg-muted/30">
                      <td className="whitespace-nowrap px-5 py-3 text-muted-foreground">{formatDateTime(r.created_at)}</td>
                      <td className="px-5 py-3">
                        <Badge tone={tone(r.action)}>{AUDIT_ACTION_LABELS[r.action] ?? r.action}</Badge>
                      </td>
                      <td className="px-5 py-3">{actor(r.actor_user_id)}</td>
                      <td className="px-5 py-3 font-mono text-xs text-muted-foreground">{r.ip_address ?? "—"}</td>
                      <td className="max-w-xs break-words px-5 py-3 text-xs text-muted-foreground">{summary(r.details) || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
        {rows && (rows.length > 0 || page > 0) && (
          <div className="flex items-center justify-between border-t border-border px-5 py-3 text-sm text-muted-foreground">
            <span>Page {page + 1}</span>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage((p) => p - 1)} aria-label="Page précédente">
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button size="sm" variant="outline" disabled={rows.length < PAGE_SIZE} onClick={() => setPage((p) => p + 1)} aria-label="Page suivante">
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </Card>
    </Page>
  );
}
