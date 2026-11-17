"use client";

import { AlertTriangle, ArrowLeft, Loader2, ScanFace, ShieldCheck, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { EnrollWizard } from "@/components/enroll-wizard";
import { FingerprintSection } from "@/components/fingerprint-section";
import { ConfirmDialog } from "@/components/modal";
import { Page } from "@/components/page";
import { useSession } from "@/components/session";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, ErrorNote, Field, Input, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/hooks";
import { CATEGORY_LABELS, POSE_LABELS, formatDateTime } from "@/lib/labels";
import type { Biometrics, ConsentText, FaceStatus, Person } from "@/lib/types";

function Section({ n, title, children, muted }: { n: number; title: string; children: React.ReactNode; muted?: boolean }) {
  return (
    <Card className={muted ? "opacity-60" : undefined}>
      <div className="flex items-center gap-3 border-b border-border px-5 py-4">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary">{n}</span>
        <h2 className="font-semibold">{title}</h2>
      </div>
      <div className="p-5">{children}</div>
    </Card>
  );
}

export default function BiometricsPage() {
  const { id } = useParams<{ id: string }>();
  const { me, orgId } = useSession();
  const toast = useToast();
  const canWrite = me.role === "super_admin" || me.role === "admin_organisation";
  const k = `${id}|${orgId ?? "me"}`;
  const [renewing, setRenewing] = useState(false);

  const person = useQuery(`bio-person|${k}`, () => api<Person>(`persons/${id}`));
  const bio = useQuery(`bio|${k}`, () => api<Biometrics>(`persons/${id}/biometrics`));
  const status = useQuery(`face-status|${k}`, () => api<FaceStatus>("face/status"));
  const needsText = bio.data && (!bio.data.consent || renewing);
  const text = useQuery(needsText ? `consent-text|${k}` : null, () => api<ConsentText>(`persons/${id}/consent-text`));

  // Tant que le moteur charge ses modèles, on revérifie son état.
  const engineReady = status.data?.ready;
  useEffect(() => {
    if (status.data === undefined || engineReady || status.data.state === "error") return;
    const t = setInterval(status.reload, 3000);
    return () => clearInterval(t);
  }, [status.data, engineReady, status.reload]);

  const [givenBy, setGivenBy] = useState<"person" | "guardian">("person");
  const [signer, setSigner] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [enrolling, setEnrolling] = useState(false);
  const [confirm, setConfirm] = useState<"consent" | "face" | null>(null);
  const [removing, setRemoving] = useState(false);

  const p = person.data;
  const fullName = p ? `${p.first_name} ${p.last_name}` : "";
  useEffect(() => {
    if (!p) return;
    const minor = p.category === "eleve";
    setGivenBy(minor ? "guardian" : "person");
    setSigner(minor ? "" : `${p.first_name} ${p.last_name}`);
  }, [p?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const reloadAll = () => {
    person.reload();
    bio.reload();
  };

  async function saveConsent(e: FormEvent) {
    e.preventDefault();
    if (!text.data) return;
    setSaving(true);
    setError(null);
    try {
      await api(`persons/${id}/consent`, {
        method: "POST",
        body: { text_version: text.data.version, accepted: true, given_by: givenBy, signer_name: signer.trim() },
      });
      toast.success(renewing ? "Consentement renouvelé" : "Consentement enregistré");
      setAccepted(false);
      setRenewing(false);
      reloadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!confirm) return;
    setRemoving(true);
    try {
      await api(confirm === "consent" ? `persons/${id}/consent` : `persons/${id}/face`, { method: "DELETE" });
      toast.success(confirm === "consent" ? "Consentement retiré et données supprimées" : "Données du visage supprimées");
      setConfirm(null);
      reloadAll();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    } finally {
      setRemoving(false);
    }
  }

  const consent = bio.data?.consent;
  const face = bio.data?.face;
  const st = status.data;
  const canEnroll = canWrite && !!consent && !!st?.ready && !!st?.encryption_configured;
  const showForm = canWrite && !!bio.data && (!consent || renewing);

  return (
    <Page>
      <Link href="/persons" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Personnes
      </Link>
      <PageHeader
        title={fullName || "Biométrie"}
        description={p ? `${p.matricule} · ${CATEGORY_LABELS[p.category] ?? p.category}` : undefined}
      />

      {(person.error || bio.error) && <ErrorNote message={person.error ?? bio.error ?? ""} onRetry={reloadAll} />}

      <div className="space-y-5">
        {st && !st.encryption_configured && (
          <div className="flex gap-3 rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" aria-hidden />
            <div className="space-y-2">
              <p className="font-medium text-destructive">Clé de chiffrement manquante</p>
              <p>
                Ajoute une ligne <code className="rounded bg-muted px-1">FACE_ENCRYPTION_KEY=…</code> dans le fichier <code className="rounded bg-muted px-1">.env</code>, puis
                redémarre l&apos;API. Pour générer la clé :
              </p>
              <pre className="overflow-x-auto rounded-lg bg-card p-3 text-xs">
                docker compose exec api python -c &quot;from app.core.crypto import generate_key; print(generate_key())&quot;
              </pre>
            </div>
          </div>
        )}
        {st && st.state === "error" && (
          <div className="flex gap-3 rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" aria-hidden />
            <div className="space-y-1">
              <p className="font-medium text-destructive">Le moteur de reconnaissance n&apos;a pas pu démarrer</p>
              <p className="break-words text-muted-foreground">{st.error}</p>
            </div>
          </div>
        )}
        {st && !st.ready && st.state !== "error" && (
          <div className="flex items-center gap-3 rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm">
            <Loader2 className="h-5 w-5 shrink-0 animate-spin" aria-hidden />
            Le moteur de reconnaissance se prépare (téléchargement des modèles au premier démarrage, environ 40 Mo)…
          </div>
        )}

        {/* 1. Consentement */}
        <Section n={1} title="Consentement">
          {bio.loading && !bio.data ? (
            <Skeleton className="h-24 w-full" />
          ) : (
            <div className="space-y-5">
              {consent && (
                <div className="space-y-3">
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-start gap-3">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-success/15 text-success">
                        <ShieldCheck className="h-5 w-5" aria-hidden />
                      </span>
                      <div className="text-sm">
                        <p className="font-medium">Consentement enregistré</p>
                        <p className="text-muted-foreground">
                          Donné par {consent.signer_name} ({consent.given_by === "guardian" ? "parent ou tuteur légal" : "la personne elle-même"}) le{" "}
                          {formatDateTime(consent.signed_at)}
                        </p>
                      </div>
                    </div>
                    {canWrite && !renewing && (
                      <Button variant="outline" size="sm" onClick={() => setConfirm("consent")}>
                        Retirer le consentement
                      </Button>
                    )}
                  </div>
                  {bio.data && !bio.data.consent_current && (
                    <div className="flex flex-col gap-3 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
                      <span>
                        Ce consentement date d&apos;avant l&apos;ajout de l&apos;empreinte. Le visage reste utilisable ; pour activer l&apos;empreinte, fais relire
                        le texte mis à jour et renouvelle le consentement.
                      </span>
                      {canWrite && !renewing && (
                        <Button size="sm" onClick={() => setRenewing(true)}>
                          Renouveler le consentement
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              )}

              {!consent && !canWrite && <p className="text-sm text-muted-foreground">Aucun consentement enregistré pour cette personne.</p>}

              {showForm && (
                <form onSubmit={saveConsent} className="space-y-4">
                  <p className="text-sm text-muted-foreground">
                    Fais lire ce texte à la personne (ou à son parent/tuteur si elle est mineure) avant toute capture.
                  </p>
                  {text.loading && !text.data ? (
                    <Skeleton className="h-40 w-full" />
                  ) : (
                    text.data && (
                      <div className="max-h-64 space-y-3 overflow-y-auto rounded-lg border border-border bg-muted/40 p-4 text-sm leading-relaxed">
                        {text.data.text.split("\n\n").map((para, i) => (
                          <p key={i}>{para}</p>
                        ))}
                      </div>
                    )
                  )}
                  <fieldset className="space-y-2">
                    <legend className="mb-1 text-sm font-medium">Consentement donné par</legend>
                    {(["person", "guardian"] as const).map((v) => (
                      <label key={v} className="flex items-center gap-2 text-sm">
                        <input
                          type="radio"
                          name="given_by"
                          checked={givenBy === v}
                          onChange={() => {
                            setGivenBy(v);
                            setSigner(v === "person" ? fullName : "");
                          }}
                          className="h-4 w-4 accent-[hsl(var(--primary))]"
                        />
                        {v === "person" ? "La personne elle-même" : "Son parent ou tuteur légal"}
                      </label>
                    ))}
                  </fieldset>
                  <Field label={givenBy === "guardian" ? "Nom du parent / tuteur" : "Nom du signataire"} htmlFor="signer">
                    <Input id="signer" value={signer} onChange={(e) => setSigner(e.target.value)} />
                  </Field>
                  <label className="flex items-start gap-2 text-sm">
                    <input type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[hsl(var(--primary))]" />
                    <span>J&apos;atteste que ce texte a été lu et que le consentement a été donné librement.</span>
                  </label>
                  {error && <ErrorNote message={error} />}
                  <div className="flex gap-2">
                    <Button type="submit" loading={saving} disabled={!accepted || signer.trim().length < 2 || !text.data}>
                      {renewing ? "Renouveler le consentement" : "Enregistrer le consentement"}
                    </Button>
                    {renewing && (
                      <Button variant="outline" onClick={() => setRenewing(false)}>
                        Annuler
                      </Button>
                    )}
                  </div>
                </form>
              )}
            </div>
          )}
        </Section>

        {/* 2. Visage */}
        <Section n={2} title="Visage" muted={!consent}>
          {!consent ? (
            <p className="text-sm text-muted-foreground">Enregistre d&apos;abord le consentement.</p>
          ) : face?.enrolled ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="success">Visage enrôlé</Badge>
                {face.poses.map((pz) => (
                  <Badge key={pz}>{POSE_LABELS[pz] ?? pz}</Badge>
                ))}
              </div>
              <p className="text-sm text-muted-foreground">Enrôlé le {formatDateTime(face.enrolled_at)}. Seul un gabarit chiffré est conservé, aucune photo.</p>
              {canWrite && (
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" onClick={() => setEnrolling(true)} disabled={!canEnroll}>
                    <ScanFace className="h-4 w-4" /> Refaire l&apos;enrôlement
                  </Button>
                  <Button variant="ghost" className="text-destructive hover:text-destructive" onClick={() => setConfirm("face")}>
                    <Trash2 className="h-4 w-4" /> Supprimer les données du visage
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                On prend 5 captures guidées : face, gauche, droite, haut et bas. Prévois une pièce bien éclairée et une personne seule devant la caméra.
              </p>
              {canWrite ? (
                <Button onClick={() => setEnrolling(true)} disabled={!canEnroll}>
                  <ScanFace className="h-4 w-4" /> Commencer l&apos;enrôlement
                </Button>
              ) : (
                <Badge tone="warning">Pas encore enrôlé</Badge>
              )}
            </div>
          )}
        </Section>

        {/* 3. Empreinte */}
        <Section n={3} title="Empreinte digitale" muted={!consent}>
          {!consent || !bio.data ? (
            <p className="text-sm text-muted-foreground">Enregistre d&apos;abord le consentement.</p>
          ) : (
            <FingerprintSection personId={id} bio={bio.data} canWrite={canWrite} onChanged={reloadAll} />
          )}
        </Section>
      </div>

      <EnrollWizard open={enrolling} personId={id} personName={fullName} onClose={() => setEnrolling(false)} onDone={reloadAll} />
      <ConfirmDialog
        open={confirm !== null}
        title={confirm === "consent" ? "Retirer le consentement ?" : "Supprimer les données du visage ?"}
        message={
          confirm === "consent"
            ? "Le gabarit du visage et les empreintes enregistrées seront supprimés immédiatement, et la personne ne pourra plus pointer tant qu'un nouveau consentement n'est pas enregistré."
            : "Le gabarit du visage sera supprimé. Le consentement reste enregistré : tu pourras refaire l'enrôlement."
        }
        confirmLabel={confirm === "consent" ? "Retirer et supprimer" : "Supprimer"}
        loading={removing}
        onConfirm={remove}
        onClose={() => setConfirm(null)}
      />
    </Page>
  );
}
