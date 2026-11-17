"use client";

import { ArrowRight, Building2, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Modal } from "@/components/modal";
import { Page } from "@/components/page";
import { useSession } from "@/components/session";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { ORG_TYPE_LABELS, formatDate } from "@/lib/labels";
import type { Organisation } from "@/lib/types";

export default function OrganisationsPage() {
  const { me, organisations, orgId, setOrgId, reloadOrganisations } = useSession();
  const router = useRouter();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [type, setType] = useState("entreprise");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (me.role !== "super_admin") {
    return <ErrorNote message="Cette page est réservée au super administrateur." />;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const org = await api<Organisation>("organisations", { method: "POST", body: { name: name.trim(), type, country: "SN" } });
      toast.success(`Organisation « ${org.name} » créée`);
      setOpen(false);
      setName("");
      reloadOrganisations();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    } finally {
      setSaving(false);
    }
  }

  function manage(org: Organisation) {
    setOrgId(org.id);
    router.push("/dashboard");
  }

  return (
    <Page>
      <PageHeader
        title="Organisations"
        description="Les clients de la plateforme. Chaque organisation a ses propres données, totalement isolées."
        actions={
          <Button onClick={() => setOpen(true)}>
            <Plus className="h-4 w-4" /> Nouvelle organisation
          </Button>
        }
      />

      <Card className="overflow-hidden">
        {organisations.length === 0 ? (
          <EmptyState
            icon={Building2}
            title="Aucune organisation"
            description="Crée la première organisation (école, entreprise, chantier...), puis un administrateur pour elle."
            action={<Button onClick={() => setOpen(true)}>Créer une organisation</Button>}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-5 py-3 font-medium">Nom</th>
                  <th className="px-5 py-3 font-medium">Type</th>
                  <th className="px-5 py-3 font-medium">Créée le</th>
                  <th className="px-5 py-3 font-medium">Statut</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {organisations.map((o) => (
                  <tr key={o.id} className="hover:bg-muted/30">
                    <td className="px-5 py-3.5 font-medium">
                      {o.name} {o.id === orgId && <Badge tone="gold">Active</Badge>}
                    </td>
                    <td className="px-5 py-3.5">{ORG_TYPE_LABELS[o.type] ?? o.type}</td>
                    <td className="px-5 py-3.5 text-muted-foreground">{formatDate(o.created_at)}</td>
                    <td className="px-5 py-3.5">
                      <Badge tone={o.status === "active" ? "success" : "neutral"}>{o.status === "active" ? "Active" : o.status}</Badge>
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <Button size="sm" variant="outline" onClick={() => manage(o)}>
                        Gérer <ArrowRight className="h-3.5 w-3.5" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Nouvelle organisation"
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Annuler
            </Button>
            <Button type="submit" form="org-form" loading={saving} disabled={name.trim().length < 2}>
              Créer
            </Button>
          </>
        }
      >
        <form id="org-form" onSubmit={onSubmit} className="space-y-4">
          <Field label="Nom" htmlFor="org-name">
            <Input id="org-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="École Sainte-Marie" />
          </Field>
          <Field label="Type" htmlFor="org-type">
            <Select id="org-type" value={type} onChange={(e) => setType(e.target.value)}>
              {Object.entries(ORG_TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          {error && <ErrorNote message={error} />}
        </form>
      </Modal>
    </Page>
  );
}
