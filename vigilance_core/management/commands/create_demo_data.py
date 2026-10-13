"""
Crée des entreprises partenaires d'exemple et des liens de dépôt sécurisés
pour tester immédiatement la plateforme en local.
"""

from django.core.management.base import BaseCommand
from vigilance_core.models import Company, DocumentRequirement, UploadRequest


class Command(BaseCommand):
    help = "Crée des entreprises et liens de dépôt de démonstration"

    def handle(self, *args, **options):
        # S'assurer que les exigences existent
        from django.core.management import call_command
        call_command('seed_requirements')

        companies_data = [
            {
                'name': "Acme BTP France",
                'siren': "552032534",
                'contact_name': "Thomas Bernard",
                'contact_email': "t.bernard@acme-btp.fr",
            },
            {
                'name': "Nexus Logistique Express",
                'siren': "803456789",
                'contact_name': "Sophie Laurent",
                'contact_email': "sophie.l@nexus-log.fr",
            },
            {
                'name': "Green Tech Services",
                'siren': "912345678",
                'contact_name': "Marc Dubois",
                'contact_email': "m.dubois@greentech.fr",
            },
        ]

        self.stdout.write(self.style.NOTICE("\n========================================================"))
        self.stdout.write(self.style.NOTICE("CRÉATION DES DONNÉES DE DÉMONSTRATION"))
        self.stdout.write(self.style.NOTICE("========================================================\n"))

        for data in companies_data:
            company, created = Company.objects.get_or_create(
                siren=data['siren'],
                defaults=data
            )
            # Génération d'un lien actif
            req = company.get_active_upload_request()
            if not req:
                req = UploadRequest.create_for_company(company, days_valid=30)

            deposit_url = f"http://127.0.0.1:8000{req.get_deposit_url()}"
            action_text = "Créée" if created else "Existante"
            self.stdout.write(f"🏢 {action_text} : {company.name} (SIREN: {company.siren})")
            self.stdout.write(f"   👉 Lien de dépôt partenaire : {deposit_url}\n")

        self.stdout.write(self.style.SUCCESS("Tableau de bord administrateur : http://127.0.0.1:8000/dashboard/"))
        self.stdout.write(self.style.SUCCESS("Console d'administration Django : http://127.0.0.1:8000/admin/ (Identifiants: admin / admin1234)\n"))
