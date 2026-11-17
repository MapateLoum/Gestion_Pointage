"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, CheckCircle2, Fingerprint, Loader2, ScanFace, ShieldAlert, XCircle, type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useWebcam } from "@/components/use-webcam";
import { WebAuthnUserError, getCredential, type RequestOptionsJSON } from "@/lib/webauthn";

type Phase = "loading" | "unpaired" | "idle" | "starting" | "capturing" | "verifying" | "fingerprint" | "success" | "failure" | "locked";

interface TerminalInfo {
  name: string;
  site_name: string | null;
  organisation_name: string;
  fingerprint_required: boolean;
  timezone: string;
}

interface Challenge {
  challenge_id: string;
  steps: string[];
  max_frames: number;
}

interface AttemptResult {
  status: "pending_fingerprint" | "success" | "failed" | "rejected";
  attempt_id: string;
  reason: string | null;
  message: string | null;
  person: { display_name: string } | null;
  webauthn: { challenge_id: string; options: RequestOptionsJSON } | null;
  record: { kind: "in" | "out"; occurred_at: string; method: string } | null;
}

class KioskHttpError extends Error {
  constructor(
    public status: number,
    message: string,
    public retryAfter?: number,
  ) {
    super(message);
  }
}

async function kioskApi<T>(path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api/kiosk/${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new KioskHttpError(0, "Connexion au serveur impossible");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : "Erreur inattendue";
    throw new KioskHttpError(res.status, detail, data?.retry_after);
  }
  return data as T;
}

const STEP_INFO: Record<string, { text: string; Icon: LucideIcon }> = {
  left: { text: "Tournez la tête vers votre gauche", Icon: ArrowLeft },
  right: { text: "Tournez la tête vers votre droite", Icon: ArrowRight },
  up: { text: "Levez le menton", Icon: ArrowUp },
  down: { text: "Baissez le menton", Icon: ArrowDown },
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function beep(ok: boolean) {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = ok ? 880 : 220;
    gain.gain.value = 0.08;
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + (ok ? 0.18 : 0.4));
    setTimeout(() => ctx.close(), 600);
  } catch {
    /* pas de son : sans importance */
  }
}

export default function KioskPage() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [info, setInfo] = useState<TerminalInfo | null>(null);
  const [segment, setSegment] = useState<{ text: string; Icon: LucideIcon; index: number; total: number } | null>(null);
  const [progress, setProgress] = useState(0);
  const [person, setPerson] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<{ ok: boolean; title: string; subtitle?: string } | null>(null);
  const [lockSeconds, setLockSeconds] = useState(0);
  const [now, setNow] = useState(() => new Date());
  const [keyInput, setKeyInput] = useState("");
  const [pairError, setPairError] = useState<string | null>(null);
  const [pairing, setPairing] = useState(false);

  const runId = useRef(0);
  const webcam = useWebcam(phase === "starting" || phase === "capturing");
  const webcamState = useRef(webcam.state);
  webcamState.current = webcam.state;
  const webcamError = useRef(webcam.error);
  webcamError.current = webcam.error;
  const capture = useRef(webcam.capture);
  capture.current = webcam.capture;

  // Horloge
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  // Le terminal est-il déjà appairé ?
  useEffect(() => {
    fetch("/api/kiosk-pair", { cache: "no-store" })
      .then(async (res) => {
        if (!res.ok) return setPhase("unpaired");
        setInfo(await res.json());
        setPhase("idle");
      })
      .catch(() => setPhase("unpaired"));
  }, []);

  // Retour automatique à l'accueil après un résultat
  useEffect(() => {
    if (phase !== "success" && phase !== "failure") return;
    const t = setTimeout(() => setPhase("idle"), phase === "success" ? 4500 : 6000);
    return () => clearTimeout(t);
  }, [phase]);

  // Compte à rebours du blocage
  useEffect(() => {
    if (phase !== "locked") return;
    if (lockSeconds <= 0) return setPhase("idle");
    const t = setTimeout(() => setLockSeconds((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [phase, lockSeconds]);

  const fail = useCallback((title: string, subtitle?: string) => {
    beep(false);
    setOutcome({ ok: false, title, subtitle });
    setPhase("failure");
  }, []);

  const handleError = useCallback(
    (e: unknown) => {
      if (e instanceof KioskHttpError) {
        if (e.status === 401) return setPhase("unpaired");
        if (e.status === 429) {
          setLockSeconds(e.retryAfter ?? 30);
          return setPhase("locked");
        }
        if (e.status === 503) return fail("Système en démarrage", "Réessayez dans un instant.");
        return fail("Pointage impossible", e.message);
      }
      fail("Pointage impossible", e instanceof Error ? e.message : undefined);
    },
    [fail],
  );

  const handleResult = useCallback(
    async (res: AttemptResult, cancelled: () => boolean): Promise<void> => {
      if (cancelled()) return;
      if (res.status === "pending_fingerprint" && res.webauthn) {
        setPerson(res.person?.display_name ?? null);
        setPhase("fingerprint");
        let credential;
        try {
          credential = await getCredential(res.webauthn.options);
        } catch (e) {
          return fail("Empreinte non lue", e instanceof WebAuthnUserError ? e.message : undefined);
        }
        if (cancelled()) return;
        const done = await kioskApi<AttemptResult>(`attempts/${res.attempt_id}/fingerprint`, { credential });
        return handleResult(done, cancelled);
      }
      if (res.status === "success" && res.record) {
        beep(true);
        const time = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: info?.timezone }).format(new Date(res.record.occurred_at));
        setOutcome({
          ok: true,
          title: res.record.kind === "in" ? "Entrée enregistrée" : "Sortie enregistrée",
          subtitle: `${res.person?.display_name ?? ""} · ${time}`,
        });
        return setPhase("success");
      }
      fail(res.message ?? "Pointage refusé");
    },
    [fail, info?.timezone],
  );

  async function start() {
    const id = ++runId.current;
    const cancelled = () => runId.current !== id;
    setPerson(null);
    setOutcome(null);
    setPhase("starting");
    try {
      const challenge = await kioskApi<Challenge>("challenges", {});
      const t0 = Date.now();
      while (webcamState.current !== "ready") {
        if (cancelled()) return;
        if (webcamState.current === "error") throw new Error(webcamError.current ?? "Caméra indisponible");
        if (Date.now() - t0 > 12_000) throw new Error("La caméra ne démarre pas");
        await sleep(150);
      }

      setPhase("capturing");
      const plan = [
        { text: "Regardez droit devant la caméra", Icon: ScanFace, ms: 1500 },
        ...challenge.steps.map((s) => ({ ...STEP_INFO[s], ms: 2600 })),
      ];
      const frames: string[] = [];
      for (let i = 0; i < plan.length; i++) {
        setSegment({ text: plan[i].text, Icon: plan[i].Icon, index: i, total: plan.length });
        const t = Date.now();
        while (Date.now() - t < plan[i].ms) {
          if (cancelled()) return;
          const frame = capture.current(640, 0.7);
          if (frame && frames.length < challenge.max_frames) frames.push(frame);
          setProgress((Date.now() - t) / plan[i].ms);
          await sleep(300);
        }
      }
      if (cancelled()) return;
      setPhase("verifying");
      const res = await kioskApi<AttemptResult>("attempts", { challenge_id: challenge.challenge_id, frames });
      await handleResult(res, cancelled);
    } catch (e) {
      if (!cancelled()) handleError(e);
    }
  }

  function cancel() {
    runId.current += 1;
    setPhase("idle");
  }

  // Entrée ou Espace pour pointer (clavier, lecteur de badge...)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (phase === "idle" && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        start();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  async function pair(e: FormEvent) {
    e.preventDefault();
    setPairing(true);
    setPairError(null);
    try {
      const res = await fetch("/api/kiosk-pair", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: keyInput }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) return setPairError(data?.detail ?? "Appairage impossible");
      setInfo(data);
      setKeyInput("");
      setPhase("idle");
    } catch {
      setPairError("Connexion au serveur impossible");
    } finally {
      setPairing(false);
    }
  }

  async function unpair() {
    if (!window.confirm("Dissocier ce terminal ? Il faudra ressaisir sa clé pour le réutiliser.")) return;
    await fetch("/api/kiosk-pair", { method: "DELETE" }).catch(() => undefined);
    setInfo(null);
    setPhase("unpaired");
  }

  const time = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: info?.timezone ?? "Africa/Dakar" }).format(now);
  const date = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long", timeZone: info?.timezone ?? "Africa/Dakar" }).format(now);
  const camera = phase === "starting" || phase === "capturing";

  return (
    <main className="relative flex min-h-screen flex-col overflow-hidden bg-sidebar text-white">
      <div className="bg-pattern absolute inset-0 opacity-60" aria-hidden />
      <div className="absolute -right-32 -top-32 h-96 w-96 rounded-full bg-accent/15 blur-3xl" aria-hidden />
      <div className="absolute -bottom-40 -left-24 h-[28rem] w-[28rem] rounded-full bg-primary/40 blur-3xl" aria-hidden />

      <header className="relative flex items-center justify-between px-8 py-6">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent text-accent-foreground">
            <Fingerprint className="h-6 w-6" aria-hidden />
          </span>
          <div className="leading-tight">
            <p className="text-lg font-semibold">{info?.organisation_name ?? "Pointage"}</p>
            <p className="text-sm text-white/60">{info ? [info.site_name, info.name].filter(Boolean).join(" · ") : "Terminal de pointage"}</p>
          </div>
        </div>
        <p className="text-sm capitalize text-white/60">{phase !== "unpaired" && phase !== "loading" ? date : ""}</p>
      </header>

      <section className="relative flex flex-1 flex-col items-center justify-center px-6 pb-10">
        <AnimatePresence mode="wait">
          {phase === "loading" && (
            <motion.div key="loading" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <Loader2 className="h-10 w-10 animate-spin text-white/70" aria-label="Chargement" />
            </motion.div>
          )}

          {phase === "unpaired" && (
            <motion.form
              key="unpaired"
              onSubmit={pair}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="w-full max-w-md space-y-5 rounded-2xl border border-white/10 bg-white/5 p-8 backdrop-blur"
            >
              <h1 className="text-2xl font-semibold">Appairer ce terminal</h1>
              <p className="text-sm text-white/70">Colle la clé du terminal, affichée une seule fois dans l&apos;administration (page Terminaux).</p>
              <input
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                placeholder="trm_…"
                autoFocus
                autoComplete="off"
                spellCheck={false}
                className="h-12 w-full rounded-lg border border-white/20 bg-black/30 px-4 font-mono text-sm placeholder:text-white/30 focus:outline-none focus:ring-2 focus:ring-accent"
              />
              {pairError && <p className="rounded-lg bg-red-500/20 px-3 py-2 text-sm text-red-200">{pairError}</p>}
              <button
                type="submit"
                disabled={!keyInput.trim() || pairing}
                className="flex h-12 w-full items-center justify-center gap-2 rounded-lg bg-accent font-semibold text-accent-foreground transition hover:brightness-110 disabled:opacity-50"
              >
                {pairing && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />} Appairer
              </button>
            </motion.form>
          )}

          {phase === "idle" && (
            <motion.div key="idle" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="flex flex-col items-center gap-8 text-center">
              <p className="font-mono text-8xl font-light tracking-tight sm:text-9xl" aria-live="off">
                {time}
              </p>
              <button
                onClick={start}
                className="group flex items-center gap-4 rounded-full bg-accent px-12 py-6 text-2xl font-semibold text-accent-foreground shadow-2xl transition hover:scale-[1.03] hover:brightness-110 focus:outline-none focus-visible:ring-4 focus-visible:ring-white/60"
              >
                <ScanFace className="h-8 w-8" aria-hidden /> Pointer
              </button>
              <p className="max-w-md text-white/60">Touchez le bouton (ou appuyez sur Entrée), regardez la caméra et suivez les consignes.</p>
            </motion.div>
          )}

          {camera && (
            <motion.div key="camera" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} className="flex w-full max-w-3xl flex-col items-center gap-5">
              <div className="relative aspect-video w-full overflow-hidden rounded-3xl border border-white/15 bg-black shadow-2xl">
                <video ref={webcam.videoRef} muted playsInline className="h-full w-full -scale-x-100 object-cover" />
                {phase === "capturing" && (
                  <svg viewBox="0 0 100 56.25" className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
                    <defs>
                      <mask id="kiosk-oval">
                        <rect width="100" height="56.25" fill="white" />
                        <ellipse cx="50" cy="28" rx="15" ry="21" fill="black" />
                      </mask>
                    </defs>
                    <rect width="100" height="56.25" fill="black" opacity="0.5" mask="url(#kiosk-oval)" />
                    <ellipse cx="50" cy="28" rx="15" ry="21" fill="none" stroke="white" strokeWidth="0.6" strokeDasharray="2 1.5" />
                  </svg>
                )}
                {phase === "starting" && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/70">
                    <Loader2 className="h-10 w-10 animate-spin" aria-hidden />
                    <p>Démarrage de la caméra…</p>
                  </div>
                )}
              </div>
              {phase === "capturing" && segment && (
                <div className="w-full space-y-3 text-center" aria-live="polite">
                  <motion.p key={segment.index} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-center gap-3 text-3xl font-semibold">
                    <segment.Icon className="h-9 w-9 text-accent" aria-hidden /> {segment.text}
                  </motion.p>
                  <div className="mx-auto h-2 w-full max-w-md overflow-hidden rounded-full bg-white/15">
                    <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${Math.min(100, ((segment.index + progress) / segment.total) * 100)}%` }} />
                  </div>
                </div>
              )}
              <button onClick={cancel} className="text-sm text-white/50 underline-offset-4 hover:text-white hover:underline">
                Annuler
              </button>
            </motion.div>
          )}

          {phase === "verifying" && (
            <motion.div key="verifying" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex flex-col items-center gap-5 text-center">
              <Loader2 className="h-16 w-16 animate-spin text-accent" aria-hidden />
              <p className="text-3xl font-semibold">Vérification…</p>
            </motion.div>
          )}

          {phase === "fingerprint" && (
            <motion.div key="fingerprint" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="flex flex-col items-center gap-6 text-center">
              <motion.span animate={{ scale: [1, 1.1, 1] }} transition={{ repeat: Infinity, duration: 1.4 }} className="text-accent">
                <Fingerprint className="h-32 w-32" aria-hidden />
              </motion.span>
              <p className="text-4xl font-semibold">Bonjour {person ?? ""}</p>
              <p className="text-2xl text-white/80">Posez votre doigt sur le lecteur</p>
            </motion.div>
          )}

          {phase === "success" && outcome && (
            <motion.div key="success" initial={{ opacity: 0, scale: 0.92 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} className="flex flex-col items-center gap-5 text-center" role="status">
              <CheckCircle2 className="h-36 w-36 text-green-400" aria-hidden />
              <p className="text-5xl font-semibold">{outcome.title}</p>
              <p className="text-3xl text-white/80">{outcome.subtitle}</p>
            </motion.div>
          )}

          {phase === "failure" && outcome && (
            <motion.div key="failure" initial={{ opacity: 0, scale: 0.92 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} className="flex max-w-xl flex-col items-center gap-5 text-center" role="alert">
              <XCircle className="h-32 w-32 text-red-400" aria-hidden />
              <p className="text-4xl font-semibold">{outcome.title}</p>
              {outcome.subtitle && <p className="text-2xl text-white/80">{outcome.subtitle}</p>}
              <button onClick={() => setPhase("idle")} className="mt-2 rounded-full bg-white/15 px-8 py-3 text-lg font-medium transition hover:bg-white/25">
                Réessayer
              </button>
            </motion.div>
          )}

          {phase === "locked" && (
            <motion.div key="locked" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex flex-col items-center gap-5 text-center" role="alert">
              <ShieldAlert className="h-28 w-28 text-amber-300" aria-hidden />
              <p className="text-4xl font-semibold">Trop d&apos;échecs</p>
              <p className="text-2xl text-white/80">Réessayez dans {lockSeconds} s</p>
            </motion.div>
          )}
        </AnimatePresence>
      </section>

      {(phase === "idle" || phase === "unpaired") && info && (
        <footer className="relative px-8 pb-5 text-right">
          <button onClick={unpair} className="text-xs text-white/30 transition hover:text-white/70">
            Dissocier ce terminal
          </button>
        </footer>
      )}
    </main>
  );
}
