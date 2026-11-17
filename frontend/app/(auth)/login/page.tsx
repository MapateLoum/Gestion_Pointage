"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Eye, EyeOff, Fingerprint, ScanFace, ShieldCheck, TimerReset } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button, Field, Input } from "@/components/ui";

const FEATURES = [
  { icon: ScanFace, text: "Reconnaissance du visage avec détection de vivacité" },
  { icon: Fingerprint, text: "Double preuve : personne ne pointe pour un autre" },
  { icon: TimerReset, text: "Présences et retards suivis en temps réel" },
  { icon: ShieldCheck, text: "Données biométriques chiffrées, conformes à la CDP" },
];

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        const detail = data?.detail;
        setError(
          res.status === 422
            ? "Vérifie le format de ton adresse email."
            : typeof detail === "string"
              ? detail
              : "Connexion impossible, réessaie.",
        );
        return;
      }
      const next = new URLSearchParams(window.location.search).get("next");
      window.location.href = next && next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
    } catch {
      setError("Impossible de joindre le serveur. Vérifie ta connexion.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <section className="relative hidden flex-col justify-between overflow-hidden bg-sidebar p-12 text-white lg:flex">
        <div className="bg-pattern absolute inset-0" aria-hidden />
        <div className="absolute -right-24 -top-24 h-72 w-72 rounded-full bg-accent/20 blur-3xl" aria-hidden />
        <div className="absolute -bottom-32 -left-16 h-80 w-80 rounded-full bg-primary/40 blur-3xl" aria-hidden />

        <div className="relative flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent text-accent-foreground">
            <Fingerprint className="h-6 w-6" aria-hidden />
          </span>
          <span className="text-lg font-semibold">Pointage</span>
        </div>

        <div className="relative max-w-md">
          <motion.h1
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="text-4xl font-semibold leading-tight"
          >
            La présence, enfin <span className="text-accent">fiable</span>.
          </motion.h1>
          <p className="mt-4 text-sidebar-foreground/75">
            Une plateforme pensée pour les écoles, entreprises et chantiers du Sénégal.
          </p>
          <ul className="mt-8 space-y-4">
            {FEATURES.map((f, i) => (
              <motion.li
                key={f.text}
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.2 + i * 0.1 }}
                className="flex items-center gap-3 text-sm"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/10">
                  <f.icon className="h-5 w-5 text-accent" aria-hidden />
                </span>
                {f.text}
              </motion.li>
            ))}
          </ul>
        </div>

        <p className="relative text-xs text-sidebar-foreground/50">© {new Date().getFullYear()} Pointage biométrique</p>
      </section>

      <section className="relative flex items-center justify-center p-6">
        <div className="absolute right-4 top-4">
          <ThemeToggle />
        </div>
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
          className="w-full max-w-sm"
        >
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <Fingerprint className="h-6 w-6" aria-hidden />
            </span>
            <span className="text-lg font-semibold">Pointage</span>
          </div>

          <h2 className="text-2xl font-semibold tracking-tight">Connexion</h2>
          <p className="mt-1 text-sm text-muted-foreground">Accède à ton espace d&apos;administration.</p>

          <form onSubmit={onSubmit} className="mt-8 space-y-5" noValidate>
            <Field label="Adresse email" htmlFor="email">
              <Input
                id="email"
                type="email"
                autoComplete="username"
                autoFocus
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="nom@organisation.sn"
              />
            </Field>
            <Field label="Mot de passe" htmlFor="password">
              <div className="relative">
                <Input
                  id="password"
                  type={show ? "text" : "password"}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="pr-11"
                />
                <button
                  type="button"
                  onClick={() => setShow((s) => !s)}
                  aria-label={show ? "Masquer le mot de passe" : "Afficher le mot de passe"}
                  className="absolute right-1 top-1 rounded-md p-2 text-muted-foreground hover:text-foreground"
                >
                  {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </Field>

            <AnimatePresence>
              {error && (
                <motion.p
                  role="alert"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className="overflow-hidden rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                >
                  {error}
                </motion.p>
              )}
            </AnimatePresence>

            <Button type="submit" loading={loading} disabled={!email || !password} className="w-full">
              Se connecter
            </Button>
          </form>
        </motion.div>
      </section>
    </div>
  );
}
