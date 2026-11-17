"use client";

import { motion } from "framer-motion";
import { Building2 } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { useSession } from "./session";
import { Card, EmptyState } from "./ui";

export function Page({ children }: { children: ReactNode }) {
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
      {children}
    </motion.div>
  );
}

/** Page réservée à une organisation précise : un super_admin doit d'abord en choisir une. */
export function RequireOrg({ children }: { children: ReactNode }) {
  const { needsOrg } = useSession();
  if (!needsOrg) return <>{children}</>;
  return (
    <Card>
      <EmptyState
        icon={Building2}
        title="Choisis une organisation"
        description="Sélectionne une organisation dans la barre du haut pour gérer ses données, ou crée-en une nouvelle."
        action={
          <Link href="/organisations" className="text-sm font-medium text-primary hover:underline">
            Voir les organisations
          </Link>
        }
      />
    </Card>
  );
}
