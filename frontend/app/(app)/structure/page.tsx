"use client";

import clsx from "clsx";
import { Building2, Layers, MapPin } from "lucide-react";
import { useState } from "react";
import { Page, RequireOrg } from "@/components/page";
import { ResourceManager, type FieldDef } from "@/components/resource-manager";
import { useSession } from "@/components/session";
import { Badge, PageHeader } from "@/components/ui";
import { KIND_LABELS } from "@/lib/labels";
import { useStructure } from "@/lib/structure-hooks";
import type { Department, Group, Site } from "@/lib/types";

type Tab = "sites" | "departments" | "groups";

const TIMEZONES = ["Africa/Dakar", "Africa/Abidjan", "Africa/Bamako", "Africa/Conakry", "Africa/Casablanca", "Europe/Paris", "UTC"];

export default function StructurePage() {
  const { me } = useSession();
  const canWrite = me.role === "super_admin" || me.role === "admin_organisation";
  const [tab, setTab] = useState<Tab>("sites");
  const s = useStructure();

  const siteOptions = (s.sites.data ?? []).map((x) => ({ value: x.id, label: x.name }));
  const deptOptions = (s.departments.data ?? []).map((x) => ({ value: x.id, label: x.name }));
  const siteName = (id: string | null) => s.sites.data?.find((x) => x.id === id)?.name ?? "—";
  const deptName = (id: string | null) => s.departments.data?.find((x) => x.id === id)?.name ?? "—";

  const siteFields: FieldDef[] = [
    { name: "name", label: "Nom", type: "text", required: true, placeholder: "Siège Dakar" },
    { name: "address", label: "Adresse", type: "text", placeholder: "Plateau, Dakar" },
    { name: "timezone", label: "Fuseau horaire", type: "select", required: true, options: TIMEZONES.map((z) => ({ value: z, label: z })) },
  ];
  const deptFields: FieldDef[] = [
    { name: "name", label: "Nom", type: "text", required: true, placeholder: "Administration" },
    { name: "site_id", label: "Site", type: "select", options: siteOptions },
  ];
  const groupFields: FieldDef[] = [
    { name: "name", label: "Nom", type: "text", required: true, placeholder: "6ème A" },
    {
      name: "kind",
      label: "Type",
      type: "select",
      required: true,
      options: Object.entries(KIND_LABELS).map(([value, label]) => ({ value, label })),
    },
    { name: "site_id", label: "Site", type: "select", options: siteOptions },
    { name: "department_id", label: "Département", type: "select", options: deptOptions },
  ];

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "sites", label: "Sites", count: s.sites.data?.length },
    { id: "departments", label: "Départements", count: s.departments.data?.length },
    { id: "groups", label: "Groupes", count: s.groups.data?.length },
  ];

  return (
    <Page>
      <PageHeader title="Structure" description="Sites, départements et groupes (classes, équipes) de l'organisation." />
      <RequireOrg>
        <div role="tablist" className="mb-5 inline-flex rounded-xl border border-border bg-muted p-1">
          {tabs.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={clsx(
                "rounded-lg px-4 py-1.5 text-sm font-medium transition",
                tab === t.id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t.label}
              {t.count !== undefined && <span className="ml-1.5 text-xs text-muted-foreground">{t.count}</span>}
            </button>
          ))}
        </div>

        {tab === "sites" && (
          <ResourceManager<Site>
            path="sites"
            singular="site"
            article="un"
            icon={MapPin}
            fields={siteFields}
            columns={[
              { header: "Nom", cell: (r) => <span className="font-medium">{r.name}</span> },
              { header: "Adresse", cell: (r) => r.address ?? "—" },
              { header: "Fuseau horaire", cell: (r) => <span className="text-muted-foreground">{r.timezone}</span> },
            ]}
            items={s.sites.data}
            loading={s.sites.loading}
            error={s.sites.error}
            canWrite={canWrite}
            toForm={(r) => ({ name: r.name, address: r.address ?? "", timezone: r.timezone })}
            defaults={{ name: "", address: "", timezone: "Africa/Dakar" }}
            deleteWarning="Les départements, groupes et personnes rattachés seront simplement détachés du site."
            onChanged={s.reloadAll}
            onRetry={s.sites.reload}
          />
        )}
        {tab === "departments" && (
          <ResourceManager<Department>
            path="departments"
            singular="département"
            article="un"
            icon={Building2}
            fields={deptFields}
            columns={[
              { header: "Nom", cell: (r) => <span className="font-medium">{r.name}</span> },
              { header: "Site", cell: (r) => siteName(r.site_id) },
            ]}
            items={s.departments.data}
            loading={s.departments.loading}
            error={s.departments.error}
            canWrite={canWrite}
            toForm={(r) => ({ name: r.name, site_id: r.site_id ?? "" })}
            defaults={{ name: "", site_id: "" }}
            deleteWarning="Les personnes rattachées seront simplement détachées du département."
            onChanged={s.reloadAll}
            onRetry={s.departments.reload}
          />
        )}
        {tab === "groups" && (
          <ResourceManager<Group>
            path="groups"
            singular="groupe"
            article="un"
            icon={Layers}
            fields={groupFields}
            columns={[
              { header: "Nom", cell: (r) => <span className="font-medium">{r.name}</span> },
              { header: "Type", cell: (r) => <Badge tone="info">{KIND_LABELS[r.kind] ?? r.kind}</Badge> },
              { header: "Site", cell: (r) => siteName(r.site_id) },
              { header: "Département", cell: (r) => deptName(r.department_id) },
            ]}
            items={s.groups.data}
            loading={s.groups.loading}
            error={s.groups.error}
            canWrite={canWrite}
            toForm={(r) => ({ name: r.name, kind: r.kind, site_id: r.site_id ?? "", department_id: r.department_id ?? "" })}
            defaults={{ name: "", kind: "equipe", site_id: "", department_id: "" }}
            deleteWarning="Les personnes ne sont pas supprimées : elles quittent seulement ce groupe."
            onChanged={s.reloadAll}
            onRetry={s.groups.reload}
          />
        )}
      </RequireOrg>
    </Page>
  );
}
