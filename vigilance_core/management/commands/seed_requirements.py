"""
Commande d'initialisation des types de documents standard pour le devoir de vigilance.
"""

from django.core.management.base import BaseCommand
from vigilance_core.models import DocumentRequirement


class Command(BaseCommand):
    help = "Initialise les exigences documentaires standard du devoir de vigilance"

    def handle(self, *args, **options):
        requirements = [
            {
                'name': "Attestation de vigilance Urssaf",
                'code': "URSSAF_VIGILANCE",
                'description': "Attestation délivrée par l'Urssaf certifiant que l'entreprise est à jour de ses cotisations sociales. Doit dater de moins de 6 mois.",
                'is_mandatory': True,
                'order': 1,
            },
            {
                'name': "Extrait Kbis ou immatriculation",
                'code': "KBIS",
                'description': "Extrait du Registre du Commerce et des Sociétés (RCS) ou extrait d'immatriculation au RNE, datant de moins de 3 mois.",
                'is_mandatory': True,
                'order': 2,
            },
            {
                'name': "Attestation d'assurance Responsabilité Civile Professionnelle",
                'code': "ASSURANCE_RC_PRO",
                'description': "Attestation d'assurance RC Pro en cours de validité pour l'exercice fiscal en cours.",
                'is_mandatory': True,
                'order': 3,
            },
        ]

        created_count = 0
        for item in requirements:
            obj, created = DocumentRequirement.objects.get_or_create(
                code=item['code'],
                defaults=item
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"Exigence créée : {obj.name}"))
            else:
                self.stdout.write(f"Exigence déjà existante : {obj.name}")

        self.stdout.write(self.style.SUCCESS(f"Initialisation terminée ({created_count} nouvelles exigences)."))
