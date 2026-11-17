"use client";

import clsx from "clsx";
import { CheckCircle2, Download, FileSpreadsheet, Upload } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { ApiError, api } from "@/lib/api";
import type { ImportResult } from "@/lib/types";
import { Modal } from "./modal";
import { Button, ErrorNote } from "./ui";

export function ImportModal({ open, onClose, onImported }: { open: boolean; onClose: () => void; onImported: (r: ImportResult) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [createGroups, setCreateGroups] = useState(false);
  const [busy, setBusy] = useState<"check" | "import" | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const reset = () => {
    setFile(null);
    setResult(null);
    setError(null);
  };
  const close = () => {
    reset();
    setCreateGroups(false);
    onClose();
  };
  const choose = (f: File | null) => {
    setFile(f);
    setResult(null);
    setError(null);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    choose(e.dataTransfer.files?.[0] ?? null);
  };

  async function run(dryRun: boolean) {
    if (!file) return;
    setBusy(dryRun ? "check" : "import");
    setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await api<ImportResult>("persons/import-csv", {
        method: "POST",
        form,
        query: { dry_run: dryRun, create_groups: createGroups },
      });
      setResult(res);
      if (!dryRun) {
        onImported(res);
        close();
      }
    } catch (e) {
      // Le fichier contient des erreurs : l'API renvoie le détail ligne par ligne.
      const body = e instanceof ApiError ? (e.body as Partial<ImportResult> | undefined) : undefined;
      if (body && Array.isArray(body.errors)) setResult(body as ImportResult);
      else setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setBusy(null);
    }
  }

  const hasErrors = !!result && result.errors.length > 0;
  const validated = !!result && result.dry_run && !hasErrors;

  return (
    <Modal
      open={open}
      onClose={close}
      size="lg"
      title="Importer des personnes"
      description="Fichier CSV (séparateur ; ou ,). Tout est vérifié avant l'import : une seule erreur et rien n'est importé."
      footer={
        <>
          <Button variant="outline" onClick={close}>
            Annuler
          </Button>
          {!validated ? (
            <Button onClick={() => run(true)} disabled={!file} loading={busy === "check"}>
              Vérifier le fichier
            </Button>
          ) : (
            <Button onClick={() => run(false)} loading={busy === "import"}>
              Importer {result?.valid_rows} personne{(result?.valid_rows ?? 0) > 1 ? "s" : ""}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-4">
        <a
          href="/api/proxy/persons/import-template"
          className="inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline"
        >
          <Download className="h-4 w-4" /> Télécharger le modèle CSV
        </a>

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => input.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
          className={clsx(
            "flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition",
            dragging ? "border-primary bg-primary/5" : "border-border hover:border-primary/50 hover:bg-muted/50",
          )}
        >
          {file ? <FileSpreadsheet className="h-8 w-8 text-primary" /> : <Upload className="h-8 w-8 text-muted-foreground" />}
          <p className="text-sm font-medium">{file ? file.name : "Glisse ton fichier ici ou clique pour le choisir"}</p>
          <p className="text-xs text-muted-foreground">
            {file ? `${(file.size / 1024).toFixed(1)} Ko` : "Colonnes : matricule, nom, prenom (obligatoires), email, telephone, categorie, site, departement, groupes"}
          </p>
          <input ref={input} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => choose(e.target.files?.[0] ?? null)} />
        </div>

        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" checked={createGroups} onChange={(e) => { setCreateGroups(e.target.checked); setResult(null); }} className="mt-0.5 h-4 w-4 accent-[hsl(var(--primary))]" />
          <span>
            Créer automatiquement les groupes absents
            <span className="block text-xs text-muted-foreground">Plusieurs groupes dans une cellule se séparent par le signe |</span>
          </span>
        </label>

        {error && <ErrorNote message={error} />}

        {validated && (
          <div className="flex items-start gap-3 rounded-lg border border-success/30 bg-success/10 px-4 py-3 text-sm">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" />
            <p>
              Fichier valide : <strong>{result.valid_rows}</strong> personne{result.valid_rows > 1 ? "s" : ""} prête{result.valid_rows > 1 ? "s" : ""} à importer
              {result.groups_created > 0 && ` et ${result.groups_created} groupe${result.groups_created > 1 ? "s" : ""} à créer`}.
            </p>
          </div>
        )}

        {hasErrors && result && (
          <div className="overflow-hidden rounded-lg border border-destructive/30">
            <div className="bg-destructive/10 px-4 py-2.5 text-sm font-medium text-destructive">
              {result.errors.length} erreur{result.errors.length > 1 ? "s" : ""} — corrige le fichier puis relance la vérification
            </div>
            <div className="max-h-56 overflow-y-auto">
              <table className="w-full text-sm">
                <tbody className="divide-y divide-border">
                  {result.errors.map((err, i) => (
                    <tr key={i}>
                      <td className="w-20 whitespace-nowrap px-4 py-2 text-muted-foreground">Ligne {err.line}</td>
                      <td className="px-4 py-2">{err.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
