"use client";

import { useEffect, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { CATEGORY_LABELS, STATUS_LABELS } from "@/lib/labels";
import type { Department, Group, Person, Site } from "@/lib/types";
import { Modal } from "./modal";
import { useToast } from "./toast";
import { Button, ErrorNote, Field, Input, Select } from "./ui";

interface FormState {
  matricule: string;
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  category: string;
  status: string;
  site_id: string;
  department_id: string;
  group_ids: string[];
}

const EMPTY: FormState = {
  matricule: "",
  first_name: "",
  last_name: "",
  email: "",
  phone: "",
  category: "employe",
  status: "active",
  site_id: "",
  department_id: "",
  group_ids: [],
};

const fromPerson = (p: Person): FormState => ({
  matricule: p.matricule,
  first_name: p.first_name,
  last_name: p.last_name,
  email: p.email ?? "",
  phone: p.phone ?? "",
  category: p.category,
  status: p.status,
  site_id: p.site_id ?? "",
  department_id: p.department_id ?? "",
  group_ids: p.group_ids,
});

export function PersonFormModal({
  open,
  person,
  sites,
  departments,
  groups,
  onClose,
  onSaved,
}: {
  open: boolean;
  person: Person | null;
  sites: Site[];
  departments: Department[];
  groups: Group[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setForm(person ? fromPerson(person) : EMPTY);
      setError(null);
    }
  }, [open, person]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }));
  const toggleGroup = (id: string) =>
    set("group_ids", form.group_ids.includes(id) ? form.group_ids.filter((g) => g !== id) : [...form.group_ids, id]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const payload = {
      matricule: form.matricule.trim(),
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      email: form.email.trim() || null,
      phone: form.phone.trim() || null,
      category: form.category,
      status: form.status,
      site_id: form.site_id || null,
      department_id: form.department_id || null,
      group_ids: form.group_ids,
    };
    try {
      if (person) await api(`persons/${person.id}`, { method: "PATCH", body: payload });
      else await api("persons", { method: "POST", body: payload });
      toast.success(person ? "Modifications enregistrées" : "Personne ajoutée");
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={person ? "Modifier la personne" : "Nouvelle personne"}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Annuler
          </Button>
          <Button type="submit" form="person-form" loading={saving} disabled={!form.matricule.trim() || !form.first_name.trim() || !form.last_name.trim()}>
            Enregistrer
          </Button>
        </>
      }
    >
      <form id="person-form" onSubmit={onSubmit} className="grid gap-4 sm:grid-cols-2">
        <Field label="Prénom *" htmlFor="p-first">
          <Input id="p-first" value={form.first_name} onChange={(e) => set("first_name", e.target.value)} autoFocus />
        </Field>
        <Field label="Nom *" htmlFor="p-last">
          <Input id="p-last" value={form.last_name} onChange={(e) => set("last_name", e.target.value)} />
        </Field>
        <Field label="Matricule *" htmlFor="p-mat" hint="Unique dans l'organisation">
          <Input id="p-mat" value={form.matricule} onChange={(e) => set("matricule", e.target.value)} placeholder="EMP001" />
        </Field>
        <Field label="Catégorie" htmlFor="p-cat">
          <Select id="p-cat" value={form.category} onChange={(e) => set("category", e.target.value)}>
            {Object.entries(CATEGORY_LABELS).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Email" htmlFor="p-email">
          <Input id="p-email" type="email" value={form.email} onChange={(e) => set("email", e.target.value)} />
        </Field>
        <Field label="Téléphone" htmlFor="p-phone">
          <Input id="p-phone" value={form.phone} onChange={(e) => set("phone", e.target.value)} placeholder="77 123 45 67" />
        </Field>
        <Field label="Site" htmlFor="p-site">
          <Select id="p-site" value={form.site_id} onChange={(e) => set("site_id", e.target.value)}>
            <option value="">— Aucun —</option>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Département" htmlFor="p-dept">
          <Select id="p-dept" value={form.department_id} onChange={(e) => set("department_id", e.target.value)}>
            <option value="">— Aucun —</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Statut" htmlFor="p-status">
          <Select id="p-status" value={form.status} onChange={(e) => set("status", e.target.value)}>
            {Object.entries(STATUS_LABELS).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </Select>
        </Field>

        <div className="sm:col-span-2">
          <p className="mb-1.5 text-sm font-medium">Groupes</p>
          {groups.length === 0 ? (
            <p className="text-sm text-muted-foreground">Aucun groupe. Crée-en dans la page Structure.</p>
          ) : (
            <div className="flex max-h-32 flex-wrap gap-2 overflow-y-auto rounded-lg border border-border p-2">
              {groups.map((g) => {
                const on = form.group_ids.includes(g.id);
                return (
                  <button
                    key={g.id}
                    type="button"
                    onClick={() => toggleGroup(g.id)}
                    aria-pressed={on}
                    className={
                      "rounded-full border px-3 py-1 text-xs font-medium transition " +
                      (on ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-muted-foreground hover:border-primary/50")
                    }
                  >
                    {g.name}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {error && (
          <div className="sm:col-span-2">
            <ErrorNote message={error} />
          </div>
        )}
      </form>
    </Modal>
  );
}
