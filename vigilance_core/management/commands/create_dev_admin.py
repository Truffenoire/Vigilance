"""
Crée un compte administrateur par défaut pour le développement local si aucun n'existe.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Crée un compte administrateur local par défaut si nécessaire"

    def add_arguments(self, parser):
        parser.add_argument('--username', default='admin', help="Nom d'utilisateur")
        parser.add_argument('--email', default='admin@vigilance.local', help="E-mail")
        parser.add_argument('--password', default='admin1234', help="Mot de passe temporaire")

    def handle(self, *args, **options):
        user_model = get_user_model()
        username = options['username']
        email = options['email']
        password = options['password']

        if not user_model.objects.filter(username=username).exists():
            user_model.objects.create_superuser(
                username=username,
                email=email,
                password=password
            )
            self.stdout.write(self.style.SUCCESS(f"Compte administrateur créé : {username} / {password}"))
        else:
            self.stdout.write(f"L'administrateur '{username}' existe déjà.")
