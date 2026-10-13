"""
Modèles pour la gestion des entreprises, des exigences documentaires,
des liens de dépôt sécurisés et des documents soumis.
"""

import re
import secrets
from datetime import timedelta
from django.db import models
from django.utils import timezone
from django.urls import reverse
from django.core.exceptions import ValidationError


def generate_secure_token() -> str:
    """Génère un jeton cryptographiquement aléatoire et non prévisible (32 octets = ~43 caractères url-safe)."""
    return secrets.token_urlsafe(32)


class DocumentRequirement(models.Model):
    """
    Type de document requis auprès des partenaires dans le cadre du devoir de vigilance.
    Exemples : Attestation Urssaf, Extrait Kbis, RC Professionnelle.
    """
    name = models.CharField(max_length=150, verbose_name="Nom du document")
    code = models.SlugField(max_length=50, unique=True, verbose_name="Code unique")
    description = models.TextField(blank=True, verbose_name="Consignes pour le partenaire")
    is_mandatory = models.BooleanField(default=True, verbose_name="Obligatoire par défaut")
    order = models.PositiveSmallIntegerField(default=0, verbose_name="Ordre d'affichage")

    class Meta:
        verbose_name = "Exigence documentaire"
        verbose_name_plural = "Exigences documentaires"
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class Company(models.Model):
    """
    Entreprise partenaire soumise au devoir de vigilance.
    """
    name = models.CharField(max_length=255, verbose_name="Raison sociale")
    siren = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="SIREN ou SIRET",
        help_text="9 chiffres pour un SIREN ou 14 chiffres pour un SIRET (espaces ignorés)"
    )
    contact_name = models.CharField(max_length=255, verbose_name="Nom du contact")
    contact_email = models.EmailField(verbose_name="Adresse e-mail de contact")
    required_documents = models.ManyToManyField(
        DocumentRequirement,
        blank=True,
        related_name="companies",
        verbose_name="Documents demandés",
        help_text="Laissez vide pour exiger l'ensemble des documents obligatoires par défaut."
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date d'enregistrement")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Dernière modification")

    class Meta:
        verbose_name = "Entreprise partenaire"
        verbose_name_plural = "Entreprises partenaires"
        ordering = ['name']

    def clean(self):
        super().clean()
        if self.siren:
            # Nettoyage des espaces
            clean_siren = re.sub(r'\s+', '', self.siren)
            if not clean_siren.isdigit():
                raise ValidationError({'siren': "Le SIREN/SIRET ne doit comporter que des chiffres."})
            if len(clean_siren) not in (9, 14):
                raise ValidationError({'siren': "Le numéro doit comporter soit 9 chiffres (SIREN), soit 14 chiffres (SIRET)."})
            self.siren = clean_siren

    def __str__(self):
        if self.siren:
            return f"{self.name} (SIREN: {self.siren})"
        return self.name

    def get_effective_requirements(self):
        """Retourne la liste des documents exigés pour cette entreprise."""
        custom = self.required_documents.all()
        if custom.exists():
            return custom
        return DocumentRequirement.objects.filter(is_mandatory=True)

    def get_active_upload_request(self):
        """Retourne la dernière demande de dépôt active si existante."""
        active_requests = self.upload_requests.filter(is_revoked=False)
        for req in active_requests.order_by('-created_at'):
            if req.is_valid():
                return req
        return None


class UploadRequest(models.Model):
    """
    Lien de dépôt individuel sécurisé délivré à une entreprise partenaire.
    Ne repose jamais sur un ID séquentiel, utilise un jeton cryptographiquement sécurisé.
    """
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="upload_requests",
        verbose_name="Entreprise partenaire"
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=generate_secure_token,
        verbose_name="Jeton de sécurité (Token)"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date de création")
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Date d'expiration",
        help_text="Laissez vide pour un lien sans date de fin automatique."
    )
    is_revoked = models.BooleanField(default=False, verbose_name="Lien révoqué")
    revoked_at = models.DateTimeField(null=True, blank=True, verbose_name="Date de révocation")
    revocation_reason = models.CharField(max_length=255, blank=True, verbose_name="Motif de révocation")
    last_accessed_at = models.DateTimeField(null=True, blank=True, verbose_name="Dernier accès")

    class Meta:
        verbose_name = "Lien de dépôt individuel"
        verbose_name_plural = "Liens de dépôt individuels"
        ordering = ['-created_at']

    def is_valid(self) -> bool:
        """Vérifie si le lien est actif et non expiré."""
        if self.is_revoked:
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return True

    def revoke(self, reason: str = ""):
        """Révoque le lien avec horodatage."""
        self.is_revoked = True
        self.revoked_at = timezone.now()
        self.revocation_reason = reason
        self.save(update_fields=['is_revoked', 'revoked_at', 'revocation_reason'])

    def get_deposit_url(self) -> str:
        """Retourne l'URL relative de dépôt."""
        return reverse('public_deposit', kwargs={'token': self.token})

    @classmethod
    def create_for_company(cls, company: Company, days_valid: int = 30) -> "UploadRequest":
        """Fabrique un nouveau lien avec expiration optionnelle."""
        expires = timezone.now() + timedelta(days=days_valid) if days_valid else None
        return cls.objects.create(
            company=company,
            token=generate_secure_token(),
            expires_at=expires
        )

    def __str__(self):
        status = "Actif" if self.is_valid() else "Inactif/Expiré"
        return f"Lien dépôt {self.company.name} ({status})"


class SubmittedDocument(models.Model):
    """
    Document professionnel déposé, tracé à travers tout le cycle de vérification et d'archivage.
    """
    class Status(models.TextChoices):
        RECU = 'RECU', 'Reçu'
        FORMAT_VALIDE = 'FORMAT_VALIDE', 'Format vérifié'
        TEXTE_EXTRAIT = 'TEXTE_EXTRAIT', 'Texte extrait'
        ARCHIVE_DRIVE = 'ARCHIVE_DRIVE', 'Archivé dans Drive'
        A_EXAMINER = 'A_EXAMINER', 'À examiner'
        ERREUR = 'ERREUR', 'Erreur'

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name="Entreprise"
    )
    requirement = models.ForeignKey(
        DocumentRequirement,
        on_delete=models.PROTECT,
        related_name="submissions",
        verbose_name="Catégorie de document"
    )
    upload_request = models.ForeignKey(
        UploadRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
        verbose_name="Lien de dépôt utilisé"
    )
    original_filename = models.CharField(max_length=255, verbose_name="Nom de fichier d'origine")
    normalized_filename = models.CharField(max_length=255, verbose_name="Nom normalisé")
    file_size_bytes = models.BigIntegerField(default=0, verbose_name="Taille (octets)")
    detected_mime_type = models.CharField(max_length=100, verbose_name="Type MIME réel détecté")
    
    # Statut du cycle de traitement
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.RECU,
        verbose_name="Statut du document",
        db_index=True
    )

    # Résultats des contrôles techniques
    technical_check_results = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Résultats des contrôles techniques"
    )

    # Résultat d'extraction de texte (stocké séparément, sans modifier le fichier)
    extracted_text = models.TextField(blank=True, default="", verbose_name="Texte extrait")
    extracted_text_char_count = models.PositiveIntegerField(default=0, verbose_name="Nombre de caractères extraits")
    has_usable_text = models.BooleanField(default=False, verbose_name="Contient du texte exploitable")

    # Destination d'archivage
    storage_backend = models.CharField(
        max_length=50,
        default="local_archive",
        verbose_name="Backend de stockage"
    )
    drive_file_id = models.CharField(max_length=255, blank=True, default="", verbose_name="ID Google Drive")
    drive_folder_id = models.CharField(max_length=255, blank=True, default="", verbose_name="ID Dossier Drive")
    local_archive_path = models.CharField(max_length=500, blank=True, default="", verbose_name="Chemin archive locale")

    # Suivi des erreurs
    error_message = models.TextField(blank=True, default="", verbose_name="Message d'erreur")

    # Horodatage
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name="Date de dépôt")
    archived_at = models.DateTimeField(null=True, blank=True, verbose_name="Date d'archivage")

    class Meta:
        verbose_name = "Document déposé"
        verbose_name_plural = "Documents déposés"
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.requirement.name} - {self.company.name} ({self.get_status_display()})"
