export type Role = "super_admin" | "admin_organisation" | "manager" | "personne" | "parent";
export type Category = "employe" | "enseignant" | "eleve" | "autre";
export type PersonStatus = "active" | "suspended";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  organisation_id: string | null;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface Organisation {
  id: string;
  name: string;
  type: string;
  country: string;
  status: string;
  created_at: string;
}

export interface Site {
  id: string;
  organisation_id: string;
  name: string;
  address: string | null;
  timezone: string;
  is_active: boolean;
  created_at: string;
}

export interface Department {
  id: string;
  organisation_id: string;
  name: string;
  site_id: string | null;
  created_at: string;
}

export interface Group {
  id: string;
  organisation_id: string;
  name: string;
  kind: string;
  site_id: string | null;
  department_id: string | null;
  created_at: string;
}

export interface Person {
  id: string;
  organisation_id: string;
  matricule: string;
  first_name: string;
  last_name: string;
  email: string | null;
  phone: string | null;
  category: Category;
  status: PersonStatus;
  site_id: string | null;
  department_id: string | null;
  group_ids: string[];
  face_enrolled: boolean;
  fingerprint_enrolled: boolean;
  consent_active: boolean;
  created_at: string;
}

export interface PersonPage {
  items: Person[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditLog {
  id: string;
  organisation_id: string | null;
  actor_user_id: string | null;
  action: string;
  object_type: string | null;
  object_id: string | null;
  ip_address: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface ImportResult {
  dry_run: boolean;
  total_rows: number;
  valid_rows: number;
  imported: number;
  groups_created: number;
  errors: { line: number; message: string }[];
}

export interface Issue {
  code: string;
  message: string;
}

export interface PoseAngles {
  yaw: number;
  pitch: number;
  roll: number;
}

export interface AnalyzeResult {
  ok: boolean;
  face_count: number;
  issues: Issue[];
  pose: PoseAngles | null;
  metrics: Record<string, number>;
}

export interface ConsentInfo {
  id: string;
  text_version: string;
  given_by: "person" | "guardian";
  signer_name: string;
  signed_at: string;
}

export interface FaceSummary {
  enrolled: boolean;
  templates: number;
  poses: string[];
  enrolled_at: string | null;
  model_name: string | null;
}

export interface FingerprintCredential {
  id: string;
  provider: string;
  label: string | null;
  created_at: string;
  last_used_at: string | null;
}

export interface FingerprintSummary {
  registered: boolean;
  credentials: FingerprintCredential[];
  max_credentials: number;
}

export interface Biometrics {
  consent: ConsentInfo | null;
  consent_current: boolean;
  current_consent_version: string;
  face: FaceSummary;
  fingerprint: FingerprintSummary;
}

export interface ConsentText {
  version: string;
  text: string;
  organisation: string;
}

export interface FaceStatus {
  state: string;
  ready: boolean;
  model_name: string;
  error: string | null;
  encryption_configured: boolean;
}

export interface EnrollResult {
  templates: number;
  poses: string[];
  average_quality: number;
}
