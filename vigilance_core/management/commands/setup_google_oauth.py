"""
Commande d'authentification interactive OAuth2 pour Google Drive.
Permet d'utiliser un compte Google personnel (@gmail.com) sans contrainte de quota.
"""

from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Configure et génère le jeton OAuth2 pour archiver sur un compte Google personnel (@gmail.com)"

    def handle(self, *args, **options):
        client_secrets_file = settings.BASE_DIR / getattr(settings, 'GOOGLE_OAUTH_CLIENT_SECRETS_FILE', 'client_secret.json')
        token_file = settings.BASE_DIR / getattr(settings, 'GOOGLE_OAUTH_TOKEN_FILE', 'token.json')

        if not client_secrets_file.exists():
            self.stdout.write(self.style.ERROR("\n❌ Fichier 'client_secret.json' introuvable à la racine du projet.\n"))
            self.stdout.write(self.style.NOTICE("POUR ARCHIVER SUR VOTRE COMPTE GOOGLE PERSONNEL (@gmail.com) :"))
            self.stdout.write("1. Rendez-vous sur Google Cloud Console :")
            self.stdout.write("   👉 https://console.cloud.google.com/apis/credentials?project=vigilance-collecte\n")
            self.stdout.write("2. Cliquez sur 'Créer des identifiants' > 'ID client OAuth'.")
            self.stdout.write("   - Type d'application : 'Application de bureau' (Desktop)")
            self.stdout.write("   - Nom : 'Vigilance Client'\n")
            self.stdout.write("   (Note : Si l'écran de consentement OAuth n'est pas configuré, choisissez 'Externe',")
            self.stdout.write("   donnez un nom et ajoutez votre adresse e-mail en 'Utilisateur test'.)\n")
            self.stdout.write("3. Téléchargez le fichier JSON d'identifiants et renommez-le :")
            self.stdout.write("   👉 client_secret.json (à déposer dans le dossier vigilance/)\n")
            self.stdout.write("4. Relancez ensuite cette commande :")
            self.stdout.write("   👉 python manage.py setup_google_oauth\n")
            return

        self.stdout.write(self.style.NOTICE("Ouverture du navigateur pour autoriser l'accès à Google Drive..."))

        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            scopes = ['https://www.googleapis.com/auth/drive']
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), scopes)
            creds = flow.run_local_server(port=0)

            with open(token_file, 'w') as f:
                f.write(creds.to_json())

            self.stdout.write(self.style.SUCCESS(f"\n✅ Authentification réussie ! Le fichier '{token_file.name}' a été créé."))
            self.stdout.write(self.style.SUCCESS("Vos dépôts seront désormais archivés directement avec votre compte Google personnel sans limite de quota.\n"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n❌ Erreur lors de l'authentification : {e}\n"))
