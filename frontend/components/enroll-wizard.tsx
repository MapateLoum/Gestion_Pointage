"use client";

import clsx from "clsx";
import { motion } from "framer-motion";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Check, CheckCircle2, Loader2, RotateCcw, ScanFace, ShieldCheck, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { POSE_LABELS } from "@/lib/labels";
import type { AnalyzeResult, EnrollResult, Issue, PoseAngles } from "@/lib/types";
import { Modal } from "./modal";
import { useToast } from "./toast";
import { Button, ErrorNote } from "./ui";
import { useWebcam } from "./use-webcam";

const POSES = ["front", "left", "right", "up", "down"] as const;
type Pose = (typeof POSES)[number];

const POSE_INFO: Record<Pose, { title: string; hint: string; Icon: LucideIcon }> = {
  front: { title: "Regarde droit devant", hint: "Visage centré dans l'ovale, bien éclairé", Icon: ScanFace },
  left: { title: "Tourne la tête vers ta gauche", hint: "Lentement, sans bouger les épaules", Icon: ArrowLeft },
  right: { title: "Tourne la tête vers ta droite", hint: "De l'autre côté, lentement", Icon: ArrowRight },
  up: { title: "Relève légèrement le menton", hint: "Garde le visage face à la caméra", Icon: ArrowUp },
  down: { title: "Baisse légèrement le menton", hint: "Garde le visage face à la caméra", Icon: ArrowDown },
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

interface Problem {
  message: string;
  poses?: Record<string, Issue[]>;
}

export function EnrollWizard({
  open,
  personId,
  personName,
  onClose,
  onDone,
}: {
  open: boolean;
  personId: string;
  personName: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [step, setStep] = useState<"capture" | "review" | "done">("capture");
  const [poseIdx, setPoseIdx] = useState(0);
  const [captures, setCaptures] = useState<Partial<Record<Pose, string>>>({});
  const [retaking, setRetaking] = useState<Pose | null>(null);
  const [feedback, setFeedback] = useState<AnalyzeResult | null>(null);
  const [serviceMessage, setServiceMessage] = useState<string | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [cameraAttempt, setCameraAttempt] = useState(0);

  // Angles de la tête déjà mesurés : servent de référence pour juger les autres poses.
  const reference = useRef<PoseAngles | null>(null);
  const angles = useRef<Partial<Record<Pose, PoseAngles>>>({});

  const webcam = useWebcam(open && step === "capture", cameraAttempt);
  const pose = POSES[poseIdx];

  // Remise à zéro à chaque ouverture : aucune image ne survit à la fermeture.
  useEffect(() => {
    if (open) {
      setStep("capture");
      setPoseIdx(0);
      setCaptures({});
      setRetaking(null);
      setFeedback(null);
      setServiceMessage(null);
      setProblem(null);
      reference.current = null;
      angles.current = {};
    }
  }, [open]);

  // Boucle d'analyse : une image toutes les ~0,5 s, validée par le serveur.
  useEffect(() => {
    if (!open || step !== "capture" || webcam.state !== "ready") return;
    let stopped = false;
    let streak = 0;
    setFeedback(null);

    (async () => {
      await sleep(700); // le temps de se mettre en position
      while (!stopped) {
        const frame = webcam.capture();
        if (!frame) {
          await sleep(300);
          continue;
        }
        try {
          const res = await api<AnalyzeResult>(`persons/${personId}/face/analyze`, {
            method: "POST",
            body: { image: frame, pose, reference: pose === "front" ? undefined : reference.current ?? undefined },
          });
          if (stopped) return;
          setServiceMessage(null);

          let issues = res.issues;
          const ref = reference.current;
          if (res.ok && res.pose && ref) {
            // Gauche/droite et haut/bas doivent être des côtés opposés.
            const partner = pose === "right" ? "left" : pose === "down" ? "up" : null;
            const axis = pose === "right" ? "yaw" : "pitch";
            const other = partner ? angles.current[partner] : undefined;
            if (other && (res.pose[axis] - ref[axis]) * (other[axis] - ref[axis]) > 0) {
              issues = [{ code: "same_direction", message: pose === "right" ? "Tourne la tête de l'autre côté" : "Incline la tête dans l'autre sens" }];
            }
          }
          const ok = res.ok && issues.length === 0;
          setFeedback({ ...res, ok, issues });

          if (ok && res.pose) {
            streak += 1;
            if (streak >= 2) {
              if (stopped) return;
              stopped = true;
              angles.current[pose] = res.pose;
              if (pose === "front") reference.current = res.pose;
              setCaptures((c) => ({ ...c, [pose]: frame }));
              if (retaking) {
                setRetaking(null);
                setStep("review");
              } else if (poseIdx < POSES.length - 1) {
                setPoseIdx((i) => i + 1);
              } else {
                setStep("review");
              }
              return;
            }
          } else {
            streak = 0;
          }
        } catch (e) {
          if (stopped) return;
          streak = 0;
          if (e instanceof ApiError && e.status === 503) {
            setServiceMessage(e.message);
            await sleep(2000);
          } else {
            setServiceMessage(e instanceof Error ? e.message : "Erreur d'analyse");
            await sleep(1500);
          }
        }
        await sleep(350);
      }
    })();

    return () => {
      stopped = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, step, poseIdx, webcam.state, personId]);

  function retake(target: Pose) {
    setRetaking(target);
    setPoseIdx(POSES.indexOf(target));
    setProblem(null);
    setStep("capture");
  }

  async function submit() {
    setSubmitting(true);
    setProblem(null);
    try {
      await api<EnrollResult>(`persons/${personId}/face/enroll`, {
        method: "POST",
        body: { images: POSES.map((p) => ({ pose: p, image: captures[p] })) },
      });
      setCaptures({}); // les images ne sont plus nécessaires
      setStep("done");
      toast.success("Visage enrôlé");
      onDone();
    } catch (e) {
      if (e instanceof ApiError) {
        const body = e.body as { poses?: Record<string, Issue[]> } | undefined;
        setProblem({ message: e.message, poses: body?.poses });
      } else {
        setProblem({ message: e instanceof Error ? e.message : "Erreur" });
      }
    } finally {
      setSubmitting(false);
    }
  }

  const info = POSE_INFO[pose];
  const good = !!feedback?.ok;
  const hasIssue = !!feedback && !feedback.ok;

  const footer =
    step === "capture" ? (
      <Button variant="outline" onClick={onClose}>
        Annuler
      </Button>
    ) : step === "review" ? (
      <>
        <Button variant="outline" onClick={onClose}>
          Annuler
        </Button>
        <Button onClick={submit} loading={submitting}>
          Enregistrer l&apos;enrôlement
        </Button>
      </>
    ) : (
      <Button onClick={onClose}>Terminer</Button>
    );

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={`Enrôlement du visage — ${personName}`}
      description="Les photos ne sont pas conservées : seul un gabarit chiffré est enregistré."
      footer={footer}
    >
      {/* Progression */}
      <ol className="mb-4 flex items-center justify-between gap-2" aria-label="Progression">
        {POSES.map((p, i) => {
          const done = !!captures[p];
          const current = step === "capture" && i === poseIdx;
          return (
            <li key={p} className="flex flex-1 flex-col items-center gap-1">
              <span
                className={clsx(
                  "flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold transition",
                  done ? "bg-success text-white" : current ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
                )}
              >
                {done ? <Check className="h-4 w-4" /> : i + 1}
              </span>
              <span className={clsx("text-xs", current ? "font-medium" : "text-muted-foreground")}>{POSE_LABELS[p]}</span>
            </li>
          );
        })}
      </ol>

      {step === "capture" && (
        <div className="space-y-3">
          <div className="relative aspect-video overflow-hidden rounded-xl bg-black">
            <video ref={webcam.videoRef} muted playsInline className="h-full w-full -scale-x-100 object-cover" />

            {webcam.state === "ready" && (
              <>
                <svg viewBox="0 0 100 56.25" className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
                  <defs>
                    <mask id="oval-mask">
                      <rect width="100" height="56.25" fill="white" />
                      <ellipse cx="50" cy="28" rx="15" ry="21" fill="black" />
                    </mask>
                  </defs>
                  <rect width="100" height="56.25" fill="black" opacity="0.45" mask="url(#oval-mask)" />
                  <ellipse
                    cx="50"
                    cy="28"
                    rx="15"
                    ry="21"
                    fill="none"
                    strokeWidth="0.7"
                    strokeDasharray={good ? undefined : "2 1.5"}
                    className={good ? "stroke-green-400" : hasIssue ? "stroke-amber-400" : "stroke-white"}
                  />
                </svg>
                <motion.div
                  key={pose}
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="absolute left-1/2 top-3 flex -translate-x-1/2 items-center gap-2 rounded-full bg-black/70 px-4 py-2 text-sm font-medium text-white backdrop-blur"
                >
                  <info.Icon className="h-4 w-4 text-accent" aria-hidden /> {info.title}
                </motion.div>
              </>
            )}

            {webcam.state !== "ready" && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-white">
                {webcam.state === "error" ? (
                  <>
                    <p className="max-w-sm text-sm">{webcam.error}</p>
                    <Button variant="outline" size="sm" onClick={() => setCameraAttempt((a) => a + 1)} className="text-foreground">
                      <RotateCcw className="h-4 w-4" /> Réessayer
                    </Button>
                  </>
                ) : (
                  <>
                    <Loader2 className="h-6 w-6 animate-spin" aria-hidden />
                    <p className="text-sm">Démarrage de la caméra… autorise-la si le navigateur le demande.</p>
                  </>
                )}
              </div>
            )}
          </div>

          <div aria-live="polite" className="min-h-[3.5rem]">
            {serviceMessage ? (
              <div className="flex items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
                <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden /> {serviceMessage}
              </div>
            ) : good ? (
              <div className="flex items-center gap-2 rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-sm text-success">
                <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden /> Parfait, ne bouge plus…
              </div>
            ) : hasIssue ? (
              <ul className="space-y-1 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
                {feedback.issues.map((i) => (
                  <li key={i.code}>{i.message}</li>
                ))}
              </ul>
            ) : (
              <p className="px-1 py-2 text-sm text-muted-foreground">{info.hint}</p>
            )}
          </div>

          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">Détails techniques</summary>
            <pre className="mt-2 overflow-x-auto rounded-lg bg-muted p-3">
              {JSON.stringify({ pose, metrics: feedback?.metrics, angles: feedback?.pose && Object.fromEntries(Object.entries(feedback.pose).map(([k, v]) => [k, Math.round(v)])) }, null, 1)}
            </pre>
          </details>
        </div>
      )}

      {step === "review" && (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">Vérifie les 5 captures. Si l&apos;une ne te convient pas, refais-la avant d&apos;enregistrer.</p>
          {problem && (
            <div className="space-y-2">
              <ErrorNote message={problem.message} />
            </div>
          )}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {POSES.map((p) => {
              const issues = problem?.poses?.[p];
              return (
                <div key={p} className="space-y-1.5">
                  <div className={clsx("relative aspect-[4/3] overflow-hidden rounded-lg border-2", issues ? "border-destructive" : "border-border")}>
                    {captures[p] && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={captures[p]} alt={`Capture ${POSE_LABELS[p]}`} className="h-full w-full -scale-x-100 object-cover" />
                    )}
                  </div>
                  <p className="text-center text-xs font-medium">{POSE_LABELS[p]}</p>
                  {issues?.map((i) => (
                    <p key={i.code} className="text-xs text-destructive">
                      {i.message}
                    </p>
                  ))}
                  <Button size="sm" variant={issues ? "primary" : "outline"} className="w-full" onClick={() => retake(p)}>
                    <RotateCcw className="h-3.5 w-3.5" /> Refaire
                  </Button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {step === "done" && (
        <div className="flex flex-col items-center gap-3 py-8 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-success/15 text-success">
            <ShieldCheck className="h-7 w-7" aria-hidden />
          </span>
          <h3 className="text-lg font-semibold">Visage enrôlé</h3>
          <p className="max-w-sm text-sm text-muted-foreground">
            Le gabarit chiffré de {personName} est enregistré. Les photos prises pendant l&apos;enrôlement ont été effacées de cet écran.
          </p>
        </div>
      )}
    </Modal>
  );
}
