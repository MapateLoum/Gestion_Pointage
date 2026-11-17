"use client";

import clsx from "clsx";
import { AlertTriangle, Check, Copy, ExternalLink, KeyRound, MonitorSmartphone, Pencil, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ConfirmDialog, Modal } from "@/components/modal";
import { Page, RequireOrg } from "@/components/page";
import { useSession } from "@/components/session";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, PageHeader, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/hooks";
import { formatDateTime } from "@/lib/labels";
import { useStructure } from "@/lib/structure-hooks";
import type { Terminal, TerminalCreated } from "@/lib/types";

const ONLINE_WINDOW_MS = 2 * 60 * 1000;

function Status({ t }: { t: Terminal }) {
  if (!t.is_active) return <Badge>Désactivé</Badge>;
  const online = t.last_seen_at && Date.now() - new Date(t.last_seen_at).getTime() < ONLINE_WINDOW_MS;
  return <Badge tone={online ? "success" : "warning"}>{online ? "En ligne" : t.last_seen_at ? "Hors ligne" : "Jamais connecté"}</Badge>;
}

export default function TerminalsPage() {
  const { me, orgId, needsOrg } = useSession();
  const toast = useToast();
  const canWrite = me.role === "super_admin" || me.role === "admin_organisation";
  const { sites } = useStructure();
  const list = useQuery(needsOrg ? null : `terminals|${orgId ?? "me"}`, () => api<Terminal[]>("terminals"));

  const [editing, setEditing] = useState<Terminal | "new" | null>(null);
  const [form, setForm] = useState({ name: "", site_id: "", fingerprint_required: true, is_active: true });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<TerminalCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const [rotating, setRotating] = useState<Terminal | null>(null);
  const [deleting, setDeleting] = useState<Terminal | null>(null);
  const [busy, setBusy] = useState(false);

  const siteName = (id: string | null) => sites.data?.find((s) => s.id === id)?.name ?? "—";

  function openForm(t: Terminal | "new") {
    setForm(
      t === "new"
        ? { name: "", site_id: "", fingerprint_required: true, is_active: true }
        : { name: t.name, site_id: t.site_id ?? "", fingerprint_required: t.fingerprint_required, is_active: t.is_active },
    );
    setError(null);
    setEditing(t);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const body = { name: form.name.trim(), site_id: form.site_id || null, fingerprint_required: form.fingerprint_required };
      if (editing === "new") {
        const res = await api<TerminalCreated>("terminals", { method: "POST", body });
        setCreated(res);
        setCopied(false);
      } else if (editing) {
        await api(`terminals/${editing.id}`, { method: "PATCH", body: { ...body, is_active: form.is_active } });
        toast.success("Terminal modifié");
      }
      setEditing(null);
      list.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    } finally {
      setSaving(false);
    }
  }

  async function rotate() {
    if (!rotating) return;
    setBusy(true);
    try {
      const res = await api<TerminalCreated>(`terminals/${rotating.id}/rotate-key`, { method: "POST" });
      setRotating(null);
      setCreated(res);
      setCopied(false);
      list.reload();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!deleting) return;
    setBusy(true);
    try {
      await api(`terminals/${deleting.id}`, { method: "DELETE" });
      toast.success("Terminal supprimé");
      setDeleting(null);
      list.reload();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }

  async function copyKey() {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied(true);
    } catch {
      toast.error("Copie impossible : sélectionne la clé et copie-la à la main");
    }
  }

  return (
    <Page>
      <PageHeader
        title="Terminaux"
        description="Les postes de pointage (tablette ou PC à l'entrée). Chacun s'identifie avec sa propre clé secrète."
        actions={
          canWrite && !needsOrg ? (
            <Button onClick={() => openForm("new")}>
              <Plus className="h-4 w-4" /> Nouveau terminal
            </Button>
          ) : undefined
        }
      />

      <RequireOrg>
        {list.error && <ErrorNote message={list.error} onRetry={list.reload} />}
        <Card className="overflow-hidden">
          {list.loading && !list.data ? (
            <div className="space-y-3 p-5">
              {[0, 1].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : list.data && list.data.length === 0 ? (
            <EmptyState
              icon={MonitorSmartphone}
              title="Aucun terminal"
              description="Crée un terminal, puis ouvre la page /kiosk sur le poste de pointage et colle sa clé."
              action={canWrite ? <Button onClick={() => openForm("new")}>Créer un terminal</Button> : undefined}
            />
          ) : (
            list.data && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="px-5 py-3 font-medium">Terminal</th>
                      <th className="px-5 py-3 font-medium">Site</th>
                      <th className="px-5 py-3 font-medium">Vérification</th>
                      <th className="px-5 py-3 font-medium">État</th>
                      <th className="px-5 py-3 font-medium">Dernière activité</th>
                      <th className="px-5 py-3" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {list.data.map((t) => (
                      <tr key={t.id} className="hover:bg-muted/30">
                        <td className="px-5 py-3">
                          <p className="font-medium">{t.name}</p>
                          <p className="font-mono text-xs text-muted-foreground">{t.key_prefix}…</p>
                        </td>
                        <td className="px-5 py-3 text-muted-foreground">{siteName(t.site_id)}</td>
                        <td className="px-5 py-3">
                          <Badge tone={t.fingerprint_required ? "info" : "warning"}>{t.fingerprint_required ? "Visage + empreinte" : "Visage seul"}</Badge>
                        </td>
                        <td className="px-5 py-3">
                          <Status t={t} />
                        </td>
                        <td className="px-5 py-3 text-muted-foreground">{formatDateTime(t.last_seen_at)}</td>
                        <td className="whitespace-nowrap px-5 py-3 text-right">
                          {canWrite && (
                            <>
                              <Button size="sm" variant="ghost" className="px-2" onClick={() => openForm(t)} aria-label={`Modifier ${t.name}`}>
                                <Pencil className="h-4 w-4" />
                              </Button>
                              <Button size="sm" variant="ghost" className="px-2" onClick={() => setRotating(t)} aria-label={`Renouveler la clé de ${t.name}`} title="Renouveler la clé">
                                <KeyRound className="h-4 w-4" />
                              </Button>
                              <Button size="sm" variant="ghost" className="px-2 text-destructive hover:text-destructive" onClick={() => setDeleting(t)} aria-label={`Supprimer ${t.name}`}>
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
        </Card>

        <Card className="mt-5 p-5 text-sm">
          <p className="font-medium">Mettre un terminal en service</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-muted-foreground">
            <li>Crée le terminal ici et copie sa clé (elle n&apos;est affichée qu&apos;une fois).</li>
            <li>
              Sur le poste de pointage, ouvre{" "}
              <a href="/kiosk" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
                /kiosk <ExternalLink className="h-3 w-3" aria-hidden />
              </a>{" "}
              et colle la clé.
            </li>
            <li>Les personnes touchent « Pointer », suivent les consignes puis posent leur doigt sur le lecteur.</li>
          </ol>
        </Card>
      </RequireOrg>

      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing === "new" ? "Nouveau terminal" : "Modifier le terminal"}
        footer={
          <>
            <Button variant="outline" onClick={() => setEditing(null)}>
              Annuler
            </Button>
            <Button type="submit" form="terminal-form" loading={saving} disabled={form.name.trim().length < 2}>
              {editing === "new" ? "Créer" : "Enregistrer"}
            </Button>
          </>
        }
      >
        <form id="terminal-form" onSubmit={save} className="space-y-4">
          <Field label="Nom" htmlFor="t-name">
            <Input id="t-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus placeholder="Entrée principale" />
          </Field>
          <Field label="Site" htmlFor="t-site" hint="Détermine le fuseau horaire utilisé pour entrées et sorties.">
            <Select id="t-site" value={form.site_id} onChange={(e) => setForm({ ...form, site_id: e.target.value })}>
              <option value="">— Aucun —</option>
              {sites.data?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          </Field>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" checked={form.fingerprint_required} onChange={(e) => setForm({ ...form, fingerprint_required: e.target.checked })} className="mt-0.5 h-4 w-4 accent-[hsl(var(--primary))]" />
            <span>
              Exiger l&apos;empreinte en plus du visage
              <span className="block text-xs text-muted-foreground">Recommandé : c&apos;est ce qui empêche de pointer pour quelqu&apos;un d&apos;autre.</span>
            </span>
          </label>
          {editing !== "new" && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} className="h-4 w-4 accent-[hsl(var(--primary))]" />
              Terminal actif
            </label>
          )}
          {error && <ErrorNote message={error} />}
        </form>
      </Modal>

      <Modal
        open={created !== null}
        onClose={() => setCreated(null)}
        title="Clé du terminal"
        footer={<Button onClick={() => setCreated(null)}>J&apos;ai copié la clé</Button>}
      >
        {created && (
          <div className="space-y-4">
            <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span>
                Cette clé n&apos;est affichée <strong>qu&apos;une seule fois</strong>. Colle-la maintenant sur le poste de pointage (page /kiosk).
              </span>
            </div>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 select-all break-all rounded-lg border border-border bg-muted px-3 py-2.5 font-mono text-sm">{created.key}</code>
              <Button variant="outline" onClick={copyKey} aria-label="Copier la clé">
                {copied ? <Check className="h-4 w-4 text-success" /> : <Copy className="h-4 w-4" />}
              </Button>
            </div>
            <p className={clsx("text-xs text-muted-foreground")}>Terminal : {created.name}</p>
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={rotating !== null}
        title="Renouveler la clé ?"
        message={`L'ancienne clé de « ${rotating?.name ?? ""} » cessera de fonctionner immédiatement : le poste devra être appairé à nouveau avec la nouvelle clé. À faire si le poste est perdu ou volé.`}
        confirmLabel="Renouveler"
        loading={busy}
        onConfirm={rotate}
        onClose={() => setRotating(null)}
      />
      <ConfirmDialog
        open={deleting !== null}
        title="Supprimer ce terminal ?"
        message={`« ${deleting?.name ?? ""} » sera supprimé et ne pourra plus pointer. L'historique des pointages est conservé.`}
        loading={busy}
        onConfirm={remove}
        onClose={() => setDeleting(null)}
      />
    </Page>
  );
}
