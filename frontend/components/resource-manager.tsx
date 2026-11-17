"use client";

import { Pencil, Plus, Trash2, type LucideIcon } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { api } from "@/lib/api";
import { ConfirmDialog, Modal } from "./modal";
import { useToast } from "./toast";
import { Button, Card, EmptyState, ErrorNote, Field, Input, Select, Skeleton } from "./ui";

export interface FieldDef {
  name: string;
  label: string;
  type: "text" | "select";
  required?: boolean;
  placeholder?: string;
  options?: { value: string; label: string }[];
}

export interface ColumnDef<T> {
  header: string;
  cell: (row: T) => ReactNode;
}

interface Props<T extends { id: string }> {
  path: string;
  singular: string;
  article: "un" | "une";
  icon: LucideIcon;
  fields: FieldDef[];
  columns: ColumnDef<T>[];
  items?: T[];
  loading: boolean;
  error?: string;
  canWrite: boolean;
  toForm: (row: T) => Record<string, string>;
  defaults: Record<string, string>;
  deleteWarning: string;
  onChanged: () => void;
  onRetry: () => void;
}

export function ResourceManager<T extends { id: string; name: string }>(props: Props<T>) {
  const { path, singular, article, icon: Icon, fields, columns, items, loading, error, canWrite } = props;
  const toast = useToast();
  const [editing, setEditing] = useState<T | "new" | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<T | null>(null);
  const [removing, setRemoving] = useState(false);

  const openNew = () => {
    setValues(props.defaults);
    setFormError(null);
    setEditing("new");
  };
  const openEdit = (row: T) => {
    setValues(props.toForm(row));
    setFormError(null);
    setEditing(row);
  };

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const payload: Record<string, string | null> = {};
    for (const f of fields) {
      const v = (values[f.name] ?? "").trim();
      if (f.required && !v) {
        setFormError(`${f.label} est obligatoire`);
        return;
      }
      payload[f.name] = v === "" ? null : v;
    }
    setSaving(true);
    setFormError(null);
    try {
      if (editing === "new") {
        await api(path, { method: "POST", body: payload });
        toast.success(`${singular.charAt(0).toUpperCase() + singular.slice(1)} créé`);
      } else if (editing) {
        await api(`${path}/${editing.id}`, { method: "PATCH", body: payload });
        toast.success("Modifications enregistrées");
      }
      setEditing(null);
      props.onChanged();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Erreur");
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    if (!deleting) return;
    setRemoving(true);
    try {
      await api(`${path}/${deleting.id}`, { method: "DELETE" });
      toast.success(`« ${deleting.name} » supprimé`);
      setDeleting(null);
      props.onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    } finally {
      setRemoving(false);
    }
  }

  return (
    <>
      {error && <ErrorNote message={error} onRetry={props.onRetry} />}
      <Card className="overflow-hidden">
        {canWrite && (
          <div className="flex justify-end border-b border-border px-5 py-3">
            <Button size="sm" onClick={openNew}>
              <Plus className="h-4 w-4" /> Ajouter {article} {singular}
            </Button>
          </div>
        )}
        {loading && !items ? (
          <div className="space-y-3 p-5">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : !items || items.length === 0 ? (
          <EmptyState
            icon={Icon}
            title={`Aucun ${singular} pour l'instant`}
            action={canWrite ? <Button onClick={openNew}>Ajouter {article} {singular}</Button> : undefined}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  {columns.map((c) => (
                    <th key={c.header} className="px-5 py-3 font-medium">
                      {c.header}
                    </th>
                  ))}
                  {canWrite && <th className="px-5 py-3" />}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {items.map((row) => (
                  <tr key={row.id} className="hover:bg-muted/30">
                    {columns.map((c) => (
                      <td key={c.header} className="px-5 py-3.5">
                        {c.cell(row)}
                      </td>
                    ))}
                    {canWrite && (
                      <td className="whitespace-nowrap px-5 py-3.5 text-right">
                        <Button size="sm" variant="ghost" onClick={() => openEdit(row)} aria-label={`Modifier ${row.name}`} className="px-2">
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setDeleting(row)} aria-label={`Supprimer ${row.name}`} className="px-2 text-destructive hover:text-destructive">
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing === "new" ? `Nouveau ${singular}` : `Modifier le ${singular}`}
        footer={
          <>
            <Button variant="outline" onClick={() => setEditing(null)}>
              Annuler
            </Button>
            <Button type="submit" form="resource-form" loading={saving}>
              Enregistrer
            </Button>
          </>
        }
      >
        <form id="resource-form" onSubmit={onSubmit} className="space-y-4">
          {fields.map((f, i) => (
            <Field key={f.name} label={f.label + (f.required ? " *" : "")} htmlFor={`f-${f.name}`}>
              {f.type === "select" ? (
                <Select id={`f-${f.name}`} value={values[f.name] ?? ""} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}>
                  {!f.required && <option value="">— Aucun —</option>}
                  {f.options?.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  id={`f-${f.name}`}
                  value={values[f.name] ?? ""}
                  placeholder={f.placeholder}
                  autoFocus={i === 0}
                  onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                />
              )}
            </Field>
          ))}
          {formError && <ErrorNote message={formError} />}
        </form>
      </Modal>

      <ConfirmDialog
        open={deleting !== null}
        title={`Supprimer ce ${singular} ?`}
        message={`« ${deleting?.name ?? ""} » sera supprimé définitivement. ${props.deleteWarning}`}
        loading={removing}
        onConfirm={onDelete}
        onClose={() => setDeleting(null)}
      />
    </>
  );
}
