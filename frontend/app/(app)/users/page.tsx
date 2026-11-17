"use client";

import { Dices, Plus, UserCog } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Modal } from "@/components/modal";
import { Page } from "@/components/page";
import { useSession } from "@/components/session";
import { useToast } from "@/components/toast";
import { Avatar, Badge, Button, Card, EmptyState, ErrorNote, Field, Input, PageHeader, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/hooks";
import { ROLE_LABELS, formatDateTime, initials } from "@/lib/labels";
import type { Role, User } from "@/lib/types";

const ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";

function generatePassword(length = 14): string {
  const bytes = crypto.getRandomValues(new Uint32Array(length));
  return Array.from(bytes, (n) => ALPHABET[n % ALPHABET.length]).join("");
}

export default function UsersPage() {
  const { me, orgId, organisations } = useSession();
  const toast = useToast();
  const isSuper = me.role === "super_admin";

  const users = useQuery(`users|${orgId ?? "all"}`, () => api<User[]>("users", { query: { limit: 200 } }));

  const roleOptions: Role[] = isSuper ? ["admin_organisation", "manager", "personne", "parent"] : ["manager", "personne", "parent"];
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ email: "", full_name: "", password: "", role: "manager" as Role, organisation_id: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const orgName = (id: string | null) => organisations.find((o) => o.id === id)?.name ?? "—";

  function openForm() {
    setForm({ email: "", full_name: "", password: generatePassword(), role: roleOptions[0], organisation_id: orgId ?? "" });
    setError(null);
    setOpen(true);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api("users", {
        method: "POST",
        body: {
          email: form.email.trim(),
          full_name: form.full_name.trim(),
          password: form.password,
          role: form.role,
          organisation_id: isSuper ? form.organisation_id || null : undefined,
        },
      });
      toast.success("Compte créé. Communique-lui son mot de passe de façon sûre.");
      setOpen(false);
      users.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    } finally {
      setSaving(false);
    }
  }

  const canSubmit = form.email.includes("@") && form.full_name.trim().length >= 2 && form.password.length >= 10 && (!isSuper || !!form.organisation_id);

  return (
    <Page>
      <PageHeader
        title="Utilisateurs"
        description="Les comptes qui peuvent se connecter à la plateforme."
        actions={
          <Button onClick={openForm}>
            <Plus className="h-4 w-4" /> Nouvel utilisateur
          </Button>
        }
      />

      {users.error && <ErrorNote message={users.error} onRetry={users.reload} />}

      <Card className="overflow-hidden">
        {users.loading && !users.data ? (
          <div className="space-y-3 p-5">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : users.data && users.data.length === 0 ? (
          <EmptyState icon={UserCog} title="Aucun utilisateur" />
        ) : (
          users.data && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-5 py-3 font-medium">Utilisateur</th>
                    <th className="px-5 py-3 font-medium">Rôle</th>
                    {isSuper && <th className="px-5 py-3 font-medium">Organisation</th>}
                    <th className="px-5 py-3 font-medium">Statut</th>
                    <th className="px-5 py-3 font-medium">Dernière connexion</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {users.data.map((u) => (
                    <tr key={u.id} className="hover:bg-muted/30">
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-3">
                          <Avatar label={initials(u.full_name)} />
                          <div className="min-w-0">
                            <p className="truncate font-medium">{u.full_name}</p>
                            <p className="truncate text-xs text-muted-foreground">{u.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-5 py-3">
                        <Badge tone={u.role === "super_admin" ? "gold" : "info"}>{ROLE_LABELS[u.role]}</Badge>
                      </td>
                      {isSuper && <td className="px-5 py-3 text-muted-foreground">{orgName(u.organisation_id)}</td>}
                      <td className="px-5 py-3">
                        <Badge tone={u.is_active ? "success" : "neutral"}>{u.is_active ? "Actif" : "Désactivé"}</Badge>
                      </td>
                      <td className="px-5 py-3 text-muted-foreground">{formatDateTime(u.last_login_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </Card>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Nouvel utilisateur"
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Annuler
            </Button>
            <Button type="submit" form="user-form" loading={saving} disabled={!canSubmit}>
              Créer le compte
            </Button>
          </>
        }
      >
        <form id="user-form" onSubmit={onSubmit} className="space-y-4">
          <Field label="Nom complet" htmlFor="u-name">
            <Input id="u-name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} autoFocus />
          </Field>
          <Field label="Adresse email" htmlFor="u-email">
            <Input id="u-email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Rôle" htmlFor="u-role">
              <Select id="u-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
                {roleOptions.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABELS[r]}
                  </option>
                ))}
              </Select>
            </Field>
            {isSuper && (
              <Field label="Organisation" htmlFor="u-org">
                <Select id="u-org" value={form.organisation_id} onChange={(e) => setForm({ ...form, organisation_id: e.target.value })}>
                  <option value="">— Choisir —</option>
                  {organisations.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
          </div>
          <Field label="Mot de passe" htmlFor="u-pass" hint="10 caractères minimum. À communiquer à la personne de façon sûre.">
            <div className="flex gap-2">
              <Input id="u-pass" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="font-mono" autoComplete="off" />
              <Button variant="outline" onClick={() => setForm({ ...form, password: generatePassword() })} aria-label="Générer un mot de passe" className="px-3">
                <Dices className="h-4 w-4" />
              </Button>
            </div>
          </Field>
          {error && <ErrorNote message={error} />}
        </form>
      </Modal>
    </Page>
  );
}
