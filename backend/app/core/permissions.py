from app.core.roles import Role

# Qui peut LIRE la structure et les personnes d'une organisation
READ_ROLES = (Role.SUPER_ADMIN, Role.ADMIN_ORGANISATION, Role.MANAGER)
# Qui peut CRÉER / MODIFIER / SUPPRIMER
WRITE_ROLES = (Role.SUPER_ADMIN, Role.ADMIN_ORGANISATION)
