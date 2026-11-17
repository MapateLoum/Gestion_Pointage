"use client";

import { Building2, Clock, Layers, MapPin, ScanFace, Upload, UserPlus, Users } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Page } from "@/components/page";
import { useSession } from "@/components/session";
import { AnimatedNumber, Card, EmptyState, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/hooks";
import type { Department, Group, PersonPage, Site } from "@/lib/types";

function Stat({ label, value, icon, loading }: { label: string; value?: number; icon: ReactNode; loading: boolean }) {
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{label}</p>
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">{icon}</span>
      </div>
      <div className="mt-3 text-3xl font-semibold tracking-tight">
        {loading || value === undefined ? <Skeleton className="h-9 w-16" /> : <AnimatedNumber value={value} />}
      </div>
    </Card>
  );
}

function QuickLink({ href, icon, children }: { href: string; icon: ReactNode; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 text-sm font-medium shadow-soft transition hover:border-primary/40 hover:bg-muted"
    >
      <span className="text-primary">{icon}</span>
      {children}
    </Link>
  );
}

export default function DashboardPage() {
  const { me, orgId, currentOrg, needsOrg, organisations } = useSession();
  const readable = me.role !== "personne" && me.role !== "parent";
  const enabled = readable && !needsOrg;
  const k = orgId ?? "none";

  const persons = useQuery(enabled ? `dash-persons|${k}` : null, () => api<PersonPage>("persons", { query: { limit: 1 } }));
  const sites = useQuery(enabled ? `dash-sites|${k}` : null, () => api<Site[]>("sites", { query: { limit: 500 } }));
  const departments = useQuery(enabled ? `dash-deps|${k}` : null, () => api<Department[]>("departments", { query: { limit: 500 } }));
  const groups = useQuery(enabled ? `dash-groups|${k}` : null, () => api<Group[]>("groups", { query: { limit: 500 } }));

  const firstName = me.full_name.split(" ")[0];
  const canWrite = me.role === "super_admin" || me.role === "admin_organisation";

  return (
    <Page>
      <PageHeader
        title={`Bonjour, ${firstName}`}
        description={currentOrg ? `Vue d'ensemble de ${currentOrg.name}` : "Vue d'ensemble de la plateforme"}
      />

      {!readable && (
        <Card>
          <EmptyState
            icon={ScanFace}
            title="Ton espace personnel arrive bientôt"
            description="Tu pourras y consulter ton historique de présence et justifier une absence."
          />
        </Card>
      )}

      {readable && needsOrg && (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Organisations" value={organisations.length} icon={<Building2 className="h-5 w-5" />} loading={false} />
          </div>
          <Card>
            <EmptyState
              icon={Building2}
              title="Choisis une organisation"
              description="Sélectionne une organisation dans la barre du haut pour voir ses personnes, sites et groupes."
              action={
                <Link href="/organisations" className="text-sm font-medium text-primary hover:underline">
                  Gérer les organisations
                </Link>
              }
            />
          </Card>
        </div>
      )}

      {enabled && (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Personnes" value={persons.data?.total} icon={<Users className="h-5 w-5" />} loading={persons.loading && !persons.data} />
            <Stat label="Sites" value={sites.data?.length} icon={<MapPin className="h-5 w-5" />} loading={sites.loading && !sites.data} />
            <Stat label="Départements" value={departments.data?.length} icon={<Building2 className="h-5 w-5" />} loading={departments.loading && !departments.data} />
            <Stat label="Groupes" value={groups.data?.length} icon={<Layers className="h-5 w-5" />} loading={groups.loading && !groups.data} />
          </div>

          {canWrite && (
            <div className="grid gap-3 sm:grid-cols-3">
              <QuickLink href="/persons" icon={<UserPlus className="h-5 w-5" />}>
                Ajouter une personne
              </QuickLink>
              <QuickLink href="/persons" icon={<Upload className="h-5 w-5" />}>
                Importer un fichier CSV
              </QuickLink>
              <QuickLink href="/structure" icon={<MapPin className="h-5 w-5" />}>
                Configurer sites et groupes
              </QuickLink>
            </div>
          )}

          <Card>
            <div className="border-b border-border px-5 py-4">
              <h2 className="font-semibold">Pointages du jour</h2>
            </div>
            <EmptyState
              icon={Clock}
              title="Bientôt disponible"
              description="Présents, retards et derniers pointages apparaîtront ici en temps réel."
            />
          </Card>
        </div>
      )}
    </Page>
  );
}
