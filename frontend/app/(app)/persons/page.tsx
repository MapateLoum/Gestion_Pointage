"use client";

import { ChevronLeft, ChevronRight, Pencil, Plus, ScanFace, Search, Trash2, Upload, Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ImportModal } from "@/components/import-modal";
import { ConfirmDialog } from "@/components/modal";
import { Page, RequireOrg } from "@/components/page";
import { PersonFormModal } from "@/components/person-form";
import { useSession } from "@/components/session";
import { useToast } from "@/components/toast";
import { Avatar, Badge, Button, Card, EmptyState, ErrorNote, Input, PageHeader, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useDebounced, useQuery } from "@/lib/hooks";
import { CATEGORY_LABELS, STATUS_LABELS, initials } from "@/lib/labels";
import { useStructure } from "@/lib/structure-hooks";
import type { ImportResult, Person, PersonPage } from "@/lib/types";

const PAGE_SIZE = 20;

export default function PersonsPage() {
  const { me, orgId, needsOrg } = useSession();
  const toast = useToast();
  const canWrite = me.role === "super_admin" || me.role === "admin_organisation";
  const { sites, departments, groups, reloadAll } = useStructure();

  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim());
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [siteId, setSiteId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [page, setPage] = useState(0);

  const [editing, setEditing] = useState<Person | "new" | null>(null);
  const [deleting, setDeleting] = useState<Person | null>(null);
  const [removing, setRemoving] = useState(false);
  const [importing, setImporting] = useState(false);

  useEffect(() => setPage(0), [q, category, status, siteId, groupId, orgId]);

  const key = needsOrg ? null : JSON.stringify(["persons", orgId, q, category, status, siteId, groupId, page]);
  const list = useQuery(key, () =>
    api<PersonPage>("persons", {
      query: {
        q: q || undefined,
        category: category || undefined,
        status: status || undefined,
        site_id: siteId || undefined,
        group_id: groupId || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      },
    }),
  );

  const data = list.data;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const siteName = (id: string | null) => sites.data?.find((s) => s.id === id)?.name ?? "—";
  const groupName = (id: string) => groups.data?.find((g) => g.id === id)?.name ?? "";
  const filtered = !!(q || category || status || siteId || groupId);

  async function onDelete() {
    if (!deleting) return;
    setRemoving(true);
    try {
      await api(`persons/${deleting.id}`, { method: "DELETE" });
      toast.success(`${deleting.first_name} ${deleting.last_name} supprimé(e)`);
      setDeleting(null);
      list.reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erreur");
    } finally {
      setRemoving(false);
    }
  }

  const onImported = (r: ImportResult) => {
    toast.success(`${r.imported} personne${r.imported > 1 ? "s" : ""} importée${r.imported > 1 ? "s" : ""}`);
    reloadAll();
    list.reload();
  };

  return (
    <Page>
      <PageHeader
        title="Personnes"
        description="Employés, enseignants et élèves qui pointent leur présence."
        actions={
          canWrite && !needsOrg ? (
            <>
              <Button variant="outline" onClick={() => setImporting(true)}>
                <Upload className="h-4 w-4" /> Importer un CSV
              </Button>
              <Button onClick={() => setEditing("new")}>
                <Plus className="h-4 w-4" /> Ajouter
              </Button>
            </>
          ) : undefined
        }
      />

      <RequireOrg>
        <Card className="mb-4 p-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <div className="relative lg:col-span-2">
              <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" aria-hidden />
              <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Rechercher un nom ou un matricule" className="pl-9" aria-label="Rechercher" />
            </div>
            <Select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Catégorie">
              <option value="">Toutes les catégories</option>
              {Object.entries(CATEGORY_LABELS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </Select>
            <Select value={groupId} onChange={(e) => setGroupId(e.target.value)} aria-label="Groupe">
              <option value="">Tous les groupes</option>
              {groups.data?.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </Select>
            <Select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Statut">
              <option value="">Tous les statuts</option>
              {Object.entries(STATUS_LABELS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </Select>
          </div>
          {(sites.data?.length ?? 0) > 0 && (
            <div className="mt-3 max-w-xs">
              <Select value={siteId} onChange={(e) => setSiteId(e.target.value)} aria-label="Site">
                <option value="">Tous les sites</option>
                {sites.data?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </Select>
            </div>
          )}
        </Card>

        {list.error && <ErrorNote message={list.error} onRetry={list.reload} />}

        <Card className="overflow-hidden">
          {list.loading && !data ? (
            <div className="space-y-3 p-5">
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : data && data.items.length === 0 ? (
            <EmptyState
              icon={Users}
              title={filtered ? "Aucun résultat" : "Aucune personne pour l'instant"}
              description={filtered ? "Essaie d'autres filtres ou une autre recherche." : "Ajoute une personne ou importe un fichier CSV pour commencer."}
              action={
                !filtered && canWrite ? (
                  <div className="flex gap-2">
                    <Button variant="outline" onClick={() => setImporting(true)}>
                      Importer un CSV
                    </Button>
                    <Button onClick={() => setEditing("new")}>Ajouter une personne</Button>
                  </div>
                ) : undefined
              }
            />
          ) : (
            data && (
              <div className={list.loading ? "overflow-x-auto opacity-60 transition-opacity" : "overflow-x-auto transition-opacity"}>
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="px-5 py-3 font-medium">Personne</th>
                      <th className="px-5 py-3 font-medium">Matricule</th>
                      <th className="px-5 py-3 font-medium">Catégorie</th>
                      <th className="px-5 py-3 font-medium">Statut</th>
                      <th className="px-5 py-3 font-medium">Biométrie</th>
                      <th className="px-5 py-3 font-medium">Site</th>
                      <th className="px-5 py-3 font-medium">Groupes</th>
                      <th className="px-5 py-3" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {data.items.map((p) => (
                      <tr key={p.id} className="hover:bg-muted/30">
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-3">
                            <Avatar label={initials(`${p.first_name} ${p.last_name}`)} />
                            <div className="min-w-0">
                              <p className="truncate font-medium">
                                {p.first_name} {p.last_name}
                              </p>
                              <p className="truncate text-xs text-muted-foreground">{p.email ?? p.phone ?? "—"}</p>
                            </div>
                          </div>
                        </td>
                        <td className="px-5 py-3 font-mono text-xs">{p.matricule}</td>
                        <td className="px-5 py-3">
                          <Badge tone="info">{CATEGORY_LABELS[p.category] ?? p.category}</Badge>
                        </td>
                        <td className="px-5 py-3">
                          <Badge tone={p.status === "active" ? "success" : "warning"}>{STATUS_LABELS[p.status] ?? p.status}</Badge>
                        </td>
                        <td className="px-5 py-3">
                          {p.consent_active ? (
                            <div className="flex flex-wrap gap-1">
                              <Badge tone={p.face_enrolled ? "success" : "warning"}>Visage</Badge>
                              <Badge tone={p.fingerprint_enrolled ? "success" : "warning"}>Empreinte</Badge>
                            </div>
                          ) : (
                            <Badge>Sans consentement</Badge>
                          )}
                        </td>
                        <td className="px-5 py-3 text-muted-foreground">{siteName(p.site_id)}</td>
                        <td className="px-5 py-3">
                          <div className="flex flex-wrap gap-1">
                            {p.group_ids.slice(0, 2).map((id) => (
                              <Badge key={id}>{groupName(id) || "…"}</Badge>
                            ))}
                            {p.group_ids.length > 2 && <Badge>+{p.group_ids.length - 2}</Badge>}
                            {p.group_ids.length === 0 && <span className="text-muted-foreground">—</span>}
                          </div>
                        </td>
                        <td className="whitespace-nowrap px-5 py-3 text-right">
                          <Link
                            href={`/persons/${p.id}/biometrics`}
                            aria-label={`Biométrie de ${p.first_name} ${p.last_name}`}
                            title="Biométrie"
                            className="inline-flex h-8 items-center rounded-lg px-2 text-primary transition hover:bg-muted"
                          >
                            <ScanFace className="h-4 w-4" />
                          </Link>
                          {canWrite && (
                            <>
                            <Button size="sm" variant="ghost" className="px-2" onClick={() => setEditing(p)} aria-label={`Modifier ${p.first_name} ${p.last_name}`}>
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button size="sm" variant="ghost" className="px-2 text-destructive hover:text-destructive" onClick={() => setDeleting(p)} aria-label={`Supprimer ${p.first_name} ${p.last_name}`}>
                              <Trash2 className="h-4 w-4" />
                            </Button>
                            </>
                          )}
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
                {data.total} personne{data.total > 1 ? "s" : ""}
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
      </RequireOrg>

      <PersonFormModal
        open={editing !== null}
        person={editing === "new" ? null : editing}
        sites={sites.data ?? []}
        departments={departments.data ?? []}
        groups={groups.data ?? []}
        onClose={() => setEditing(null)}
        onSaved={list.reload}
      />
      <ImportModal open={importing} onClose={() => setImporting(false)} onImported={onImported} />
      <ConfirmDialog
        open={deleting !== null}
        title="Supprimer cette personne ?"
        message={`${deleting?.first_name ?? ""} ${deleting?.last_name ?? ""} (${deleting?.matricule ?? ""}) sera supprimé(e) définitivement.`}
        loading={removing}
        onConfirm={onDelete}
        onClose={() => setDeleting(null)}
      />
    </Page>
  );
}
