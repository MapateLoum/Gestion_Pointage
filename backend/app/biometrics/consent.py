"""Texte de consentement biométrique. Le texte affiché ET son empreinte (SHA-256) sont conservés
avec chaque consentement : on peut prouver plus tard exactement ce que la personne a accepté.

⚠ Modèle à faire relire par un juriste et à confronter aux recommandations de la CDP
(loi n° 2008-12 sur la protection des données à caractère personnel) avant toute mise en production.
"""
import hashlib

CONSENT_VERSION = "v2"

_TEMPLATE = """\
Responsable du traitement : {organisation}.

Finalité. Vos données biométriques servent uniquement à enregistrer votre présence (pointage) et à empêcher qu'une autre personne pointe à votre place. Elles ne sont utilisées pour aucun autre but et ne sont jamais vendues ni transmises à des tiers.

Données collectées. Un gabarit mathématique de votre visage, calculé à partir de quelques photos prises pendant l'enrôlement ; les photos elles-mêmes ne sont pas conservées, seul le gabarit chiffré est enregistré. Si {organisation} utilise aussi l'empreinte digitale, un identifiant de sécurité lié à votre empreinte est enregistré : votre empreinte elle-même reste dans l'appareil qui la lit et n'est pas copiée sur nos serveurs.

Durée de conservation. Vos données sont conservées tant que vous faites partie de {organisation}, puis supprimées à votre départ.

Vos droits. Vous pouvez à tout moment demander l'accès à vos données, leur correction ou leur suppression, et retirer ce consentement. Le retrait du consentement entraîne la suppression immédiate de votre gabarit de visage et de votre identifiant d'empreinte. Vous pouvez vous adresser à {organisation} ou à la Commission de Protection des Données Personnelles (CDP) du Sénégal.

Libre choix. Ce consentement est libre : un refus ne doit entraîner aucune sanction, et {organisation} doit vous proposer une autre solution de pointage.

Pour les personnes mineures, ce consentement doit être donné par leur parent ou tuteur légal.
"""


def render(organisation_name: str) -> str:
    return _TEMPLATE.format(organisation=organisation_name)


def template_sha256() -> str:
    return hashlib.sha256(_TEMPLATE.encode()).hexdigest()
