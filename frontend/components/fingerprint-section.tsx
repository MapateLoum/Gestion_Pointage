"use client";

import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Fingerprint, Info, Loader2, ShieldCheck, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import type { Biometrics, FingerprintCredential } from "@/lib/types";
import {
  WebAuthnUserError,
  createCredential,
  getCredential,
  platformAuthenticatorAvailable,
  webauthnSupported,
  type CreationOptionsJSON,
  type RequestOptionsJSON,
} from "@/lib/webauthn";
import { ConfirmDialog, Modal } from "./modal";
import { useToast } from "./toast";
import { Button, ErrorNote, Field, Input } from "./ui";

type Phase = "idle" | "register" | "test";

export function FingerprintSection({
  personId,
  bio,
  canWrite,
  onChanged,
}: {
  personId: string;
  bio: Biometrics;
  canWrite: boolean;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [phase, setPhase] = useState<Phase>("idle");
  const [labelOpen, setLabelOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [deleting, setDeleting] = useState<FingerprintCredential | null>(null);
  const [removing, setRemoving] = useState(false);
  const [available, setAvailable] = useState<boolean | null>(null);

  useEffect(() => {
    platformAuthenticatorAvailable().then(setAvailable);
  }, []);

  const wrongHost = typeof window !== "undefined" && window.location.hostname === "127.0.0.1";
  const fp = bio.fingerprint;
  const ready = bio.consent_current && available === true && !wrongHost;
  const busy = phase !== "idle";

  const message = (e: unknown) => (e instanceof WebAuthnUserError || e instanceof Error ? e.message : "Erreur");

  async function register() {
    setLabelOpen(false);
    setPhase("register");
    setResult(null);
    try {
      const { challenge_id, options } = await api<{ challenge_id: string; options: CreationOptionsJSON }>(
        `persons/${personId}/fingerprint/register/options`,
        { method: "POST" },
      );
      const credential = await createCredential(options); // la fenêtre Windows s'ouvre ici
      await api(`persons/${personId}/fingerprint/register/verify`, {
        method: "POST",
        body: { challenge_id, credential, label: label.trim() || undefined },
      });
      setLabel("");
      toast.success("Empreinte enregistrée");
      onChanged();
    } catch (e) {
      setResult({ ok: false, text: message(e) });
    } finally {
      setPhase("idle");
    }
  }

  async function test() {
    setPhase("test");
    setResult(null);
    try {
      const { challenge_id, options } = await api<{ challenge_id: string; options: RequestOptionsJSON }>(
        `persons/${personId}/fingerprint/authenticate/options`,
        { method: "POST" },
      );
      const credential = await getCredential(options);
      const res = await api<{ verified: boolean; label: string | null }>(`persons/${personId}/fingerprint/authenticate/verify`, {
        method: "POST",
        body: { challenge_id, credential },
      });
      setResult({ ok: res.verified, text: `Empreinte reconnue${res.label ? ` (${res.label})` : ""} : elle appartient bien à cette personne.` });
      onChanged();
    } catch (e) {
      setResult({ ok: false, text: message(e) });
    } finally {
      setPhase("idle");
    }
  }

  async function remove() {
    if (!deleting) return;
    setRemoving(true);
    try {
      await api(`persons/${personId}/fingerprint/${deleting.id}`, { method: "DELETE" });
      toast.success("Empreinte supprimée");
      setDeleting(null);
      onChanged();
    } catch (e) {
      toast.error(message(e));
    } finally {
      setRemoving(false);
    }
  }

  return (
    <div className="space-y-4">
      {wrongHost && (
        <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>
            Tu utilises l&apos;adresse 127.0.0.1 : le navigateur refusera l&apos;empreinte. Ouvre le site avec <strong>http://localhost:3000</strong>.
          </span>
        </div>
      )}
      {available === false && (
        <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>
            {webauthnSupported()
              ? "Aucun lecteur d'empreinte utilisable sur cet appareil. Configure Windows Hello (Paramètres > Comptes > Options de connexion > Reconnaissance d'empreinte digitale)."
              : "Ce navigateur ne gère pas l'empreinte (WebAuthn)."}
          </span>
        </div>
      )}
      {!bio.consent_current && bio.consent && (
        <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>Le texte de consentement a été mis à jour pour mentionner l&apos;empreinte. Renouvelle le consentement (section 1) pour l&apos;activer.</span>
        </div>
      )}

      {fp.registered ? (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {fp.credentials.map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="flex items-center gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-success/15 text-success">
                  <ShieldCheck className="h-5 w-5" aria-hidden />
                </span>
                <div className="text-sm">
                  <p className="font-medium">{c.label ?? "Empreinte"}</p>
                  <p className="text-xs text-muted-foreground">
                    Enregistrée le {formatDateTime(c.created_at)}
                    {c.last_used_at ? ` · dernier test ${formatDateTime(c.last_used_at)}` : ""}
                  </p>
                </div>
              </div>
              {canWrite && (
                <Button size="sm" variant="ghost" className="px-2 text-destructive hover:text-destructive" onClick={() => setDeleting(c)} aria-label="Supprimer cette empreinte">
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          Aucune empreinte enregistrée. L&apos;empreinte est le deuxième facteur : elle doit correspondre à la même personne que le visage.
        </p>
      )}

      {busy && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center gap-4 rounded-xl border border-primary/30 bg-primary/5 px-4 py-4"
          role="status"
        >
          <motion.span animate={{ scale: [1, 1.12, 1] }} transition={{ repeat: Infinity, duration: 1.4 }} className="text-primary">
            <Fingerprint className="h-10 w-10" aria-hidden />
          </motion.span>
          <div className="text-sm">
            <p className="font-medium">{phase === "register" ? "Enregistrement de l'empreinte…" : "Vérification de l'empreinte…"}</p>
            <p className="text-muted-foreground">Une fenêtre Windows s&apos;ouvre : pose ton doigt sur le lecteur.</p>
          </div>
          <Loader2 className="ml-auto h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
        </motion.div>
      )}

      {result && !busy && (
        <div
          role="status"
          className={
            "flex items-start gap-2 rounded-lg border px-3 py-2 text-sm " +
            (result.ok ? "border-success/30 bg-success/10 text-success" : "border-destructive/30 bg-destructive/10 text-destructive")
          }
        >
          {result.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />}
          <span>{result.text}</span>
        </div>
      )}

      {canWrite && (
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setLabelOpen(true)} disabled={!ready || busy || fp.credentials.length >= fp.max_credentials}>
            <Fingerprint className="h-4 w-4" /> {fp.registered ? "Ajouter une empreinte" : "Enregistrer une empreinte"}
          </Button>
          {fp.registered && (
            <Button variant="outline" onClick={test} disabled={!ready || busy}>
              Tester l&apos;empreinte
            </Button>
          )}
        </div>
      )}

      <details className="rounded-lg bg-muted/50 px-4 py-3 text-sm text-muted-foreground">
        <summary className="flex cursor-pointer items-center gap-2 font-medium text-foreground">
          <Info className="h-4 w-4" aria-hidden /> Bon à savoir
        </summary>
        <ul className="mt-3 list-disc space-y-1.5 pl-5">
          <li>L&apos;empreinte est lue par ton appareil (Windows Hello) : elle n&apos;est jamais envoyée au serveur, seule une preuve cryptographique l&apos;est.</li>
          <li>Pose bien ton <strong>doigt</strong>. Si Windows propose le code PIN, ce n&apos;est pas une vérification biométrique.</li>
          <li>L&apos;empreinte est liée à cet appareil. Pour d&apos;autres bornes de pointage, il faudra l&apos;enregistrer sur chacune, ou utiliser un lecteur USB dédié.</li>
          <li>Windows Hello accepte toutes les empreintes enregistrées sur le PC : avec un seul PC partagé pour tester, c&apos;est la limite attendue.</li>
        </ul>
      </details>

      <Modal
        open={labelOpen}
        onClose={() => setLabelOpen(false)}
        size="sm"
        title="Enregistrer une empreinte"
        footer={
          <>
            <Button variant="outline" onClick={() => setLabelOpen(false)}>
              Annuler
            </Button>
            <Button onClick={register}>Continuer</Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Nom de l'empreinte (facultatif)" htmlFor="fp-label" hint="Par exemple : index droit">
            <Input id="fp-label" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={100} autoFocus />
          </Field>
          <p className="text-sm text-muted-foreground">Quand tu cliques sur Continuer, Windows ouvre sa fenêtre : pose le doigt de la personne sur le lecteur.</p>
          {result && !result.ok && <ErrorNote message={result.text} />}
        </div>
      </Modal>

      <ConfirmDialog
        open={deleting !== null}
        title="Supprimer cette empreinte ?"
        message={`« ${deleting?.label ?? "Empreinte"} » sera supprimée. La personne ne pourra plus l'utiliser pour pointer.`}
        loading={removing}
        onConfirm={remove}
        onClose={() => setDeleting(null)}
      />
    </div>
  );
}
