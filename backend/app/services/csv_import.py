"""Lecture et validation d'un fichier CSV de personnes.

Règle : tout ou rien. Si UNE ligne est invalide, rien n'est importé et on renvoie
la liste des erreurs avec le numéro de ligne, pour que l'admin corrige son fichier.
"""
import csv
import io
import re
import unicodedata
import uuid
from dataclasses import dataclass, field

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Department, Group, Person, Site

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
GROUP_SEPARATOR = "|"

REQUIRED_COLUMNS = {"matricule", "nom", "prenom"}
KNOWN_COLUMNS = REQUIRED_COLUMNS | {
    "email", "telephone", "categorie", "site", "departement", "groupes",
}
CATEGORIES = {"employe", "enseignant", "eleve", "autre"}

MATRICULE_RE = re.compile(r"^[A-Za-z0-9._/\-]{1,50}$")
PHONE_RE = re.compile(r"^[0-9+()\-\s.]{6,30}$")
_email_adapter = TypeAdapter(EmailStr)

TEMPLATE = (
    "matricule;nom;prenom;email;telephone;categorie;site;departement;groupes\n"
    "EMP001;Diop;Awa;awa.diop@exemple.sn;77 123 45 67;enseignant;Siège Dakar;Administration;6eA|Maths\n"
)


def norm(value: str | None) -> str:
    """minuscules, sans accents, espaces nettoyés : « Département » -> « departement »."""
    text = unicodedata.normalize("NFKD", (value or "").strip())
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


@dataclass
class RowError:
    line: int
    message: str


@dataclass
class ParsedRow:
    line: int
    matricule: str
    last_name: str
    first_name: str
    email: str | None
    phone: str | None
    category: str
    site_id: uuid.UUID | None
    department_id: uuid.UUID | None
    group_keys: list[str]


@dataclass
class ParseResult:
    total_rows: int = 0
    rows: list[ParsedRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    new_groups: dict[str, str] = field(default_factory=dict)  # clé normalisée -> nom affiché


def decode_csv(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")  # Excel ajoute souvent un BOM
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def parse_csv(db: Session, org_id: uuid.UUID, raw: bytes, *, create_groups: bool) -> ParseResult:
    result = ParseResult()
    text = decode_csv(raw)
    first_line = text.splitlines()[0] if text.strip() else ""
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        result.errors.append(RowError(1, "Fichier vide"))
        return result
    reader.fieldnames = [norm(h) for h in reader.fieldnames]
    missing = REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing:
        result.errors.append(
            RowError(1, "Colonnes obligatoires manquantes : " + ", ".join(sorted(missing)))
        )
        return result

    sites = {norm(s.name): s.id for s in db.scalars(select(Site).where(Site.organisation_id == org_id))}
    departments = {
        norm(d.name): d.id for d in db.scalars(select(Department).where(Department.organisation_id == org_id))
    }
    groups = {norm(g.name): g.id for g in db.scalars(select(Group).where(Group.organisation_id == org_id))}
    existing = set(db.scalars(select(Person.matricule).where(Person.organisation_id == org_id)))
    seen: dict[str, int] = {}

    try:
        for row in reader:
            line = reader.line_num
            if not any((v or "").strip() for k, v in row.items() if k):
                continue  # ligne vide
            result.total_rows += 1
            if result.total_rows > MAX_ROWS:
                result.errors.append(RowError(line, f"Trop de lignes (maximum {MAX_ROWS})"))
                return result

            def cell(name: str) -> str:
                return (row.get(name) or "").strip()

            problems: list[str] = []
            matricule = cell("matricule")
            if not MATRICULE_RE.match(matricule):
                problems.append("matricule invalide (lettres, chiffres, . _ / - ; 50 max)")
            elif matricule in existing:
                problems.append(f"matricule {matricule} déjà utilisé")
            elif matricule in seen:
                problems.append(f"matricule {matricule} en double (déjà ligne {seen[matricule]})")
            else:
                seen[matricule] = line

            last_name, first_name = cell("nom"), cell("prenom")
            if not last_name or len(last_name) > 100:
                problems.append("nom manquant ou trop long")
            if not first_name or len(first_name) > 100:
                problems.append("prénom manquant ou trop long")

            email = cell("email") or None
            if email:
                try:
                    email = _email_adapter.validate_python(email).lower()
                except ValidationError:
                    problems.append(f"email invalide : {email}")

            phone = cell("telephone") or None
            if phone and not PHONE_RE.match(phone):
                problems.append(f"téléphone invalide : {phone}")

            category = norm(cell("categorie")) or "employe"
            if category not in CATEGORIES:
                problems.append("catégorie invalide (employe, enseignant, eleve, autre)")

            site_id = department_id = None
            if cell("site"):
                site_id = sites.get(norm(cell("site")))
                if site_id is None:
                    problems.append(f"site inconnu : {cell('site')}")
            if cell("departement"):
                department_id = departments.get(norm(cell("departement")))
                if department_id is None:
                    problems.append(f"département inconnu : {cell('departement')}")

            group_keys: list[str] = []
            for name in filter(None, (g.strip() for g in cell("groupes").split(GROUP_SEPARATOR))):
                key = norm(name)
                if key in groups:
                    group_keys.append(key)
                elif create_groups:
                    result.new_groups.setdefault(key, name)
                    group_keys.append(key)
                else:
                    problems.append(f"groupe inconnu : {name}")

            if problems:
                result.errors.append(RowError(line, " ; ".join(problems)))
                continue
            result.rows.append(
                ParsedRow(line, matricule, last_name, first_name, email, phone, category,
                          site_id, department_id, group_keys)
            )
    except csv.Error as exc:
        result.errors.append(RowError(reader.line_num, f"Fichier CSV illisible : {exc}"))
    return result
