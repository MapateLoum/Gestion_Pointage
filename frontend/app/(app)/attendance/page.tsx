"use client";

import clsx from "clsx";
import { ChevronLeft, ChevronRight, Clock, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Page, RequireOrg } from "@/components/page";
import { useSession } from "@/components/session";
import { Badge, Button, Card, EmptyState, ErrorNote, Input, PageHeader, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/hooks";
import {
  ATTEMPT_REASON_LABELS,
  ATTEMPT_STATUS_LABELS,
  METHOD_LABELS,
  formatDateTime,
  formatTime,
  todayInDakar,
} from "@/lib/labels";
import type { AttemptRow, AttendancePage } from "@/lib/types";

const PAGE_SIZE = 25;
const REFRESH_MS = 15_000;

function statusTone(status: string) {
  if (status === "success") return "success" as const;
  if (status.startsWith("failed")) return "danger" as const;
  if (status === "rejected") return "warning" as const;
  return "neutral" as const;
}

export default function AttendancePage() {
  const { me, orgId, needsOrg } = useSession();
  const isAdmin = me.role === "super_admin" || me.role === "admin_organisation";
  const [tab, setTab] = useState<"records" | "attempts">("records");
  const [day, setDay] = useState(todayInDakar());
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [day, kind, status, tab, orgId]);

  const records = useQuery(needsOrg || tab !== "records" ? null : JSON.stringify(["att", orgId, day, kind, page]), () =>
    api<AttendancePage>("attendance", { query: { date: day, kind: kind || undefined, limit: PAGE_SIZE, offset: page * PAGE_SIZE } }),
  );
  const attempts = useQuery(needsOrg || tab !== "attempts" || !isAdmin ? null : JSON.stringify(["attempts", orgId, status, page]), () =>
    api<AttemptRow[]>("attendance/attempts", { query: { status: status || undefined, limit: PAGE_SIZE, offset: page * PAGE_SIZE } }),
  );

  // Rafraîchissement automatique : les nouveaux pointages apparaissent sans recharger la page.
  const active = tab === "records" ? records : attempts;
  useEffect(() => {
    if (needsOrg) return;
    const t = setInterval(active.reload, REFRESH_MS);
    return () => clearInterval(t);
  }, [active.reload, needsOrg]);

  const data = records.data;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <Page>
      <PageHeader
        title="Pointages"
        description="Entrées et sorties enregistrées par les terminaux."
        actions={
          <Button variant="outline" onClick={active.reload} loading={active.loading && !!(data || attempts.data)}>
            <RefreshCw className="h-4 w-4" /> Actualiser
          </Button>
        }
      />

      <RequireOrg>
        {isAdmin && (
          <div role="tablist" className="mb-5 inline-flex rounded-xl border border-border bg-muted p-1">
            {([["records", "Pointages"], ["attempts", "Tentatives"]] as const).map(([id, label]) => (
              <button
                key={id}
                role="tab"
                aria-selected={tab === id}
                onClick={() => setTab(id)}
                className={clsx(
                  "rounded-lg px-4 py-1.5 text-sm font-medium transition",
                  tab === id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        )}

        {tab === "records" && (
          <>
            <Card className="mb-4 p-3">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Input type="date" value={day} max={todayInDakar()} onChange={(e) => e.target.value && setDay(e.target.value)} aria-label="Jour" />
                <Select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Type">
                  <option value="">Entrées et sorties</option>
                  <option value="in">Entrées</option>
                  <option value="out">Sorties</option>
                </Select>
              </div>
            </Card>
            {records.error && <ErrorNote message={records.error} onRetry={records.reload} />}
            <Card className="overflow-hidden">
              {records.loading && !data ? (
                <div className="space-y-3 p-5">
                  {[0, 1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : data && data.items.length === 0 ? (
                <EmptyState icon={Clock} title="Aucun pointage ce jour-là" description="Les pointages apparaissent ici dès qu'une personne pointe sur un terminal." />
              ) : (
                data && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                        <tr>
                          <th className="px-5 py-3 font-medium">Heure</th>
                          <th className="px-5 py-3 font-medium">Personne</th>
                          <th className="px-5 py-3 font-medium">Type</th>
                          <th className="px-5 py-3 font-medium">Terminal</th>
                          <th className="px-5 py-3 font-medium">Vérification</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {data.items.map((r) => (
                          <tr key={r.id} className="hover:bg-muted/30">
                            <td className="whitespace-nowrap px-5 py-3 font-mono">{formatTime(r.occurred_at)}</td>
                            <td className="px-5 py-3">
                              <p className="font-medium">{r.person_name}</p>
                              <p className="font-mono text-xs text-muted-foreground">{r.matricule}</p>
                            </td>
                            <td className="px-5 py-3">
                              <Badge tone={r.kind === "in" ? "success" : "gold"}>{r.kind === "in" ? "Entrée" : "Sortie"}</Badge>
                            </td>
                            <td className="px-5 py-3 text-muted-foreground">{r.terminal_name ?? "—"}</td>
                            <td className="px-5 py-3">
                              <Badge tone={r.method === "face+fingerprint" ? "info" : "warning"}>{METHOD_LABELS[r.method] ?? r.method}</Badge>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )
              )}
              {data && data.total > 0 && (
                <div className="flex items-center justify-between border-t border-border px-5 py-3 text-sm text-muted-foreground">
                  <span>
                    {data.total} pointage{data.total > 1 ? "s" : ""}
                  </span>
                  <div className="flex items-center gap-2">
                    <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage((p) => p - 1)} aria-label="Page précédente">
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <span>
                      Page {page + 1} / {totalPages}
                    </span>
                    <Button size="sm" variant="outline" disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)} aria-label="Page suivante">
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </Card>
          </>
        )}

        {tab === "attempts" && isAdmin && (
          <>
            <Card className="mb-4 p-3">
              <div className="max-w-xs">
                <Select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Résultat">
                  <option value="">Toutes les tentatives</option>
                  {Object.entries(ATTEMPT_STATUS_LABELS).map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </Select>
              </div>
            </Card>
            <p className="mb-3 text-sm text-muted-foreground">
              Toutes les tentatives, réussies ou non, avec les scores de reconnaissance (de 0 à 1) : utile pour régler les seuils et repérer les fraudes.
            </p>
            {attempts.error && <ErrorNote message={attempts.error} onRetry={attempts.reload} />}
            <Card className="overflow-hidden">
              {attempts.loading && !attempts.data ? (
                <div className="space-y-3 p-5">
                  {[0, 1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : attempts.data && attempts.data.length === 0 ? (
                <EmptyState icon={Clock} title="Aucune tentative" />
              ) : (
                attempts.data && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                        <tr>
                          <th className="px-5 py-3 font-medium">Date</th>
                          <th className="px-5 py-3 font-medium">Terminal</th>
                          <th className="px-5 py-3 font-medium">Personne</th>
                          <th className="px-5 py-3 font-medium">Résultat</th>
                          <th className="px-5 py-3 font-medium">Raison</th>
                          <th className="px-5 py-3 font-medium">Score</th>
                          <th className="px-5 py-3 font-medium">Écart</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {attempts.data.map((a) => (
                          <tr key={a.id} className="hover:bg-muted/30">
                            <td className="whitespace-nowrap px-5 py-3 text-muted-foreground">{formatDateTime(a.created_at)}</td>
                            <td className="px-5 py-3">{a.terminal_name ?? "—"}</td>
                            <td className="px-5 py-3">{a.person_name ?? "—"}</td>
                            <td className="px-5 py-3">
                              <Badge tone={statusTone(a.status)}>{ATTEMPT_STATUS_LABELS[a.status] ?? a.status}</Badge>
                            </td>
                            <td className="px-5 py-3 text-muted-foreground">{a.reason ? ATTEMPT_REASON_LABELS[a.reason] ?? a.reason : "—"}</td>
                            <td className="px-5 py-3 font-mono">{a.face_score?.toFixed(2) ?? "—"}</td>
                            <td className="px-5 py-3 font-mono">{a.face_margin?.toFixed(2) ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )
              )}
              <div className="flex items-center justify-between border-t border-border px-5 py-3 text-sm text-muted-foreground">
                <span>Page {page + 1}</span>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage((p) => p - 1)} aria-label="Page précédente">
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <Button size="sm" variant="outline" disabled={!attempts.data || attempts.data.length < PAGE_SIZE} onClick={() => setPage((p) => p + 1)} aria-label="Page suivante">
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </Card>
          </>
        )}
      </RequireOrg>
    </Page>
  );
}
