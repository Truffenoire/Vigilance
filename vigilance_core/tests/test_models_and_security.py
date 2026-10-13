"""
Tests automatisés des modèles et de la sécurité des jetons d'accès.
"""

from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.urls import reverse
from vigilance_core.models import (
    Company,
    DocumentRequirement,
    UploadRequest,
    SubmittedDocument,
    generate_secure_token
)


class CompanyModelTest(TestCase):
    def test_company_creation_and_str(self):
        company = Company.objects.create(
            name="Acme Corp",
            siren="123456789",
            contact_name="Alice Dupont",
            contact_email="alice@acme.test"
        )
        self.assertIn("Acme Corp", str(company))
        self.assertIn("123456789", str(company))

    def test_siren_space_stripping_and_clean(self):
        company = Company(
            name="Espaces Corp",
            siren=" 123 456 789 ",
            contact_name="Bob",
            contact_email="bob@test.fr"
        )
        company.clean()
        self.assertEqual(company.siren, "123456789")

    def test_invalid_siren_raises_validation_error(self):
        # Longueur incorrecte (ex: 5 chiffres)
        bad_company = Company(
            name="Bad Siren Corp",
            siren="12345",
            contact_name="Bob",
            contact_email="bob@test.fr"
        )
        with self.assertRaises(ValidationError):
            bad_company.clean()

        # Caractères non numériques
        letters_company = Company(
            name="Letters Corp",
            siren="12345678A",
            contact_name="Bob",
            contact_email="bob@test.fr"
        )
        with self.assertRaises(ValidationError):
            letters_company.clean()

    def test_effective_requirements(self):
        r1 = DocumentRequirement.objects.create(name="Urssaf", code="URSSAF", is_mandatory=True)
        r2 = DocumentRequirement.objects.create(name="Kbis", code="KBIS", is_mandatory=True)
        r3 = DocumentRequirement.objects.create(name="Optionnel", code="OPT", is_mandatory=False)

        company = Company.objects.create(
            name="Test Requirements",
            contact_name="Claire",
            contact_email="claire@test.fr"
        )
        # Par défaut, prend les exigences obligatoires
        default_reqs = list(company.get_effective_requirements())
        self.assertIn(r1, default_reqs)
        self.assertIn(r2, default_reqs)
        self.assertNotIn(r3, default_reqs)

        # Si on spécifie une exigence particulière
        company.required_documents.add(r3)
        custom_reqs = list(company.get_effective_requirements())
        self.assertIn(r3, custom_reqs)
        self.assertEqual(len(custom_reqs), 1)


class UploadRequestSecurityTest(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Nexus Tech",
            siren="987654321",
            contact_name="Marc",
            contact_email="marc@nexus.test"
        )

    def test_token_entropy_and_uniqueness(self):
        tokens = {generate_secure_token() for _ in range(200)}
        self.assertEqual(len(tokens), 200, "Tous les jetons générés doivent être strictement uniques.")
        for token in tokens:
            self.assertGreaterEqual(len(token), 40, "Le jeton doit avoir une entropie élevée (>= 40 chars url-safe).")
            # Ne doit pas être un nombre séquentiel ou prévisible
            self.assertFalse(token.isdigit())

    def test_upload_request_validity_lifecycle(self):
        # 1. Requête active par défaut
        req = UploadRequest.create_for_company(self.company, days_valid=7)
        self.assertTrue(req.is_valid())

        # 2. Expiration
        req.expires_at = timezone.now() - timedelta(minutes=1)
        req.save()
        self.assertFalse(req.is_valid(), "Une demande avec date d'expiration passée doit être invalide.")

        # 3. Révocation
        req.expires_at = timezone.now() + timedelta(days=1)
        req.revoke(reason="Révocation manuelle test")
        self.assertFalse(req.is_valid(), "Une demande révoquée doit être invalide.")
        self.assertTrue(req.is_revoked)
        self.assertIsNotNone(req.revoked_at)
        self.assertEqual(req.revocation_reason, "Révocation manuelle test")

    def test_deposit_url_generation(self):
        req = UploadRequest.create_for_company(self.company)
        expected_url = reverse('public_deposit', kwargs={'token': req.token})
        self.assertEqual(req.get_deposit_url(), expected_url)


class SubmittedDocumentModelTest(TestCase):
    def test_document_creation_and_status(self):
        company = Company.objects.create(name="Doc Test", contact_name="A", contact_email="a@test.fr")
        req_type = DocumentRequirement.objects.create(name="Urssaf", code="URSSAF", is_mandatory=True)
        upload_req = UploadRequest.create_for_company(company)

        doc = SubmittedDocument.objects.create(
            company=company,
            requirement=req_type,
            upload_request=upload_req,
            original_filename="attestation_2026.pdf",
            normalized_filename="2026_URSSAF_DocTest.pdf",
            file_size_bytes=102400,
            detected_mime_type="application/pdf",
            status=SubmittedDocument.Status.RECU
        )
        self.assertEqual(doc.status, SubmittedDocument.Status.RECU)
        self.assertEqual(doc.storage_backend, "local_archive")
        self.assertIn("Urssaf", str(doc))
