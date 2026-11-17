from enum import StrEnum


class Role(StrEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN_ORGANISATION = "admin_organisation"
    MANAGER = "manager"
    PERSONNE = "personne"
    PARENT = "parent"


# Rôles qu'un admin d'organisation a le droit de créer dans SON organisation.
ORG_ADMIN_CREATABLE_ROLES = {Role.MANAGER, Role.PERSONNE, Role.PARENT}
