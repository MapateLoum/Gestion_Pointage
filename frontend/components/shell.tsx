"use client";

import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import {
  Building2,
  ChevronsLeft,
  ChevronsRight,
  Fingerprint,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
  ScrollText,
  UserCog,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { ROLE_LABELS, initials } from "@/lib/labels";
import type { Role } from "@/lib/types";
import { useSession } from "./session";
import { ThemeToggle } from "./theme-toggle";
import { Avatar, Select } from "./ui";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  roles: Role[];
}

const ALL: Role[] = ["super_admin", "admin_organisation", "manager", "personne", "parent"];
const ADMINS: Role[] = ["super_admin", "admin_organisation"];

const NAV: NavItem[] = [
  { href: "/dashboard", label: "Tableau de bord", icon: LayoutDashboard, roles: ALL },
  { href: "/organisations", label: "Organisations", icon: Building2, roles: ["super_admin"] },
  { href: "/structure", label: "Structure", icon: Network, roles: [...ADMINS, "manager"] },
  { href: "/persons", label: "Personnes", icon: Users, roles: [...ADMINS, "manager"] },
  { href: "/users", label: "Utilisateurs", icon: UserCog, roles: ADMINS },
  { href: "/audit", label: "Journal d'audit", icon: ScrollText, roles: ADMINS },
];

function Nav({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const { me } = useSession();
  return (
    <nav className="flex-1 space-y-1 px-3 py-4" aria-label="Navigation principale">
      {NAV.filter((item) => item.roles.includes(me.role)).map((item) => {
        const active = pathname === item.href || pathname.startsWith(item.href + "/");
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            title={collapsed ? item.label : undefined}
            aria-current={active ? "page" : undefined}
            className={clsx(
              "group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition",
              active ? "bg-white/10 text-white" : "text-sidebar-foreground/75 hover:bg-white/5 hover:text-white",
              collapsed && "justify-center px-0",
            )}
          >
            {active && <span className="absolute left-0 top-2 h-6 w-1 rounded-r bg-accent" aria-hidden />}
            <item.icon className="h-5 w-5 shrink-0" aria-hidden />
            {!collapsed && <span className="truncate">{item.label}</span>}
          </Link>
        );
      })}
    </nav>
  );
}

function Brand({ collapsed }: { collapsed: boolean }) {
  return (
    <div className={clsx("flex items-center gap-3 px-5 py-5", collapsed && "justify-center px-0")}>
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent text-accent-foreground">
        <Fingerprint className="h-5 w-5" aria-hidden />
      </span>
      {!collapsed && (
        <span className="leading-tight">
          <span className="block text-sm font-semibold text-white">Pointage</span>
          <span className="block text-xs text-sidebar-foreground/60">Visage + empreinte</span>
        </span>
      )}
    </div>
  );
}

function UserBox({ collapsed }: { collapsed: boolean }) {
  const { me, logout } = useSession();
  return (
    <div className="border-t border-white/10 p-3">
      <div className={clsx("flex items-center gap-3 rounded-lg p-2", collapsed && "justify-center")}>
        <Avatar label={initials(me.full_name)} className="bg-white/15 text-white" />
        {!collapsed && (
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-white">{me.full_name}</p>
            <p className="truncate text-xs text-sidebar-foreground/60">{ROLE_LABELS[me.role]}</p>
          </div>
        )}
        {!collapsed && (
          <button
            onClick={logout}
            aria-label="Se déconnecter"
            className="rounded-md p-2 text-sidebar-foreground/70 transition hover:bg-white/10 hover:text-white"
          >
            <LogOut className="h-4 w-4" />
          </button>
        )}
      </div>
      {collapsed && (
        <button
          onClick={logout}
          aria-label="Se déconnecter"
          className="mt-1 flex w-full justify-center rounded-md p-2 text-sidebar-foreground/70 transition hover:bg-white/10 hover:text-white"
        >
          <LogOut className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { me, organisations, orgId, setOrgId } = useSession();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [drawer, setDrawer] = useState(false);

  useEffect(() => setCollapsed(localStorage.getItem("sidebar") === "collapsed"), []);
  useEffect(() => setDrawer(false), [pathname]);

  const toggleCollapsed = () => {
    const next = !collapsed;
    setCollapsed(next);
    localStorage.setItem("sidebar", next ? "collapsed" : "open");
  };

  return (
    <div className="min-h-screen">
      {/* Barre latérale (ordinateur) */}
      <aside
        className={clsx(
          "fixed inset-y-0 left-0 z-30 hidden flex-col bg-sidebar transition-[width] duration-200 lg:flex",
          collapsed ? "w-[72px]" : "w-64",
        )}
      >
        <Brand collapsed={collapsed} />
        <Nav collapsed={collapsed} />
        <button
          onClick={toggleCollapsed}
          className="mx-3 mb-2 flex items-center justify-center rounded-lg p-2 text-sidebar-foreground/60 transition hover:bg-white/5 hover:text-white"
          aria-label={collapsed ? "Déplier le menu" : "Replier le menu"}
        >
          {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
        </button>
        <UserBox collapsed={collapsed} />
      </aside>

      {/* Tiroir (mobile) */}
      <AnimatePresence>
        {drawer && (
          <motion.div className="fixed inset-0 z-40 lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <div className="absolute inset-0 bg-black/50" onClick={() => setDrawer(false)} aria-hidden />
            <motion.aside
              initial={{ x: -280 }}
              animate={{ x: 0 }}
              exit={{ x: -280 }}
              transition={{ type: "spring", damping: 30, stiffness: 320 }}
              className="relative flex h-full w-64 flex-col bg-sidebar"
            >
              <button
                onClick={() => setDrawer(false)}
                className="absolute right-3 top-4 rounded-md p-1.5 text-sidebar-foreground/70 hover:bg-white/10"
                aria-label="Fermer le menu"
              >
                <X className="h-5 w-5" />
              </button>
              <Brand collapsed={false} />
              <Nav collapsed={false} onNavigate={() => setDrawer(false)} />
              <UserBox collapsed={false} />
            </motion.aside>
          </motion.div>
        )}
      </AnimatePresence>

      <div className={clsx("transition-[padding] duration-200", collapsed ? "lg:pl-[72px]" : "lg:pl-64")}>
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-border bg-background/85 px-4 backdrop-blur sm:px-6">
          <button
            onClick={() => setDrawer(true)}
            className="rounded-lg p-2 hover:bg-muted lg:hidden"
            aria-label="Ouvrir le menu"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex-1" />
          {me.role === "super_admin" && (
            <Select
              aria-label="Organisation active"
              value={orgId ?? ""}
              onChange={(e) => setOrgId(e.target.value || null)}
              className="h-9 w-48 sm:w-64"
            >
              <option value="">Toutes les organisations</option>
              {organisations.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </Select>
          )}
          <ThemeToggle />
        </header>
        <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-8">{children}</main>
      </div>
    </div>
  );
}
