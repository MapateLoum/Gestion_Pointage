import type { Role } from "./types";

export const ROLE_LABELS: Record<Role, string> = {
  super_admin: "Super administrateur",
  admin_organisation: "Administrateur",
  manager: "Manager",
  personne: "Personne",
  parent: "Parent",
};

export const CATEGORY_LABELS: Record<string, string> = {
  employe: "Employé",
  enseignant: "Enseignant",
  eleve: "Élève",
  autre: "Autre",
};

export const STATUS_LABELS: Record<string, string> = {
  active: "Actif",
  suspended: "Suspendu",
};

export const KIND_LABELS: Record<string, string> = {
  classe: "Classe",
  equipe: "Équipe",
  autre: "Autre",
};

export const ORG_TYPE_LABELS: Record<string, string> = {
  ecole: "École",
  entreprise: "Entreprise",
  chantier: "Chantier",
  centre_formation: "Centre de formation",
  autre: "Autre",
};

export const AUDIT_ACTION_LABELS: Record<string, string> = {
  "auth.login_success": "Connexion réussie",
  "auth.login_failed": "Connexion échouée",
  "auth.login_blocked": "Connexion bloquée (compte verrouillé)",
  "auth.account_locked": "Compte verrouillé",
  "auth.token_refreshed": "Session renouvelée",
  "auth.refresh_reuse_detected": "Réutilisation de jeton détectée",
  "auth.logout": "Déconnexion",
  "user.created": "Utilisateur créé",
  "user.super_admin_created": "Super administrateur créé",
  "organisation.created": "Organisation créée",
  "site.created": "Site créé",
  "site.updated": "Site modifié",
  "site.deleted": "Site supprimé",
  "department.created": "Département créé",
  "department.updated": "Département modifié",
  "department.deleted": "Département supprimé",
  "group.created": "Groupe créé",
  "group.updated": "Groupe modifié",
  "group.deleted": "Groupe supprimé",
  "person.created": "Personne créée",
  "person.updated": "Personne modifiée",
  "person.deleted": "Personne supprimée",
  "person.imported": "Import CSV de personnes",
  "consent.recorded": "Consentement biométrique enregistré",
  "consent.revoked": "Consentement biométrique retiré",
  "consent.superseded": "Consentement renouvelé (nouveau texte)",
  "face.enrolled": "Visage enrôlé",
  "fingerprint.registered": "Empreinte enregistrée",
  "fingerprint.verified": "Empreinte vérifiée (test)",
  "fingerprint.verify_failed": "Vérification d'empreinte échouée",
  "fingerprint.counter_regression": "Empreinte : compteur anormal (clone possible)",
  "fingerprint.deleted": "Empreinte supprimée",
  "face.deleted": "Données du visage supprimées",
  "face.duplicate_rejected": "Enrôlement refusé : visage déjà connu",
};

const dateTime = new Intl.DateTimeFormat("fr-FR", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Africa/Dakar",
});
const dateOnly = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeZone: "Africa/Dakar" });

export const formatDateTime = (iso: string | null | undefined) => (iso ? dateTime.format(new Date(iso)) : "—");
export const formatDate = (iso: string | null | undefined) => (iso ? dateOnly.format(new Date(iso)) : "—");

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() || "?";
}

export const POSE_LABELS: Record<string, string> = {
  front: "Face",
  left: "Gauche",
  right: "Droite",
  up: "Haut",
  down: "Bas",
};
