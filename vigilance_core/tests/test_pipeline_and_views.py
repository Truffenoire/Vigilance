"""
Tests automatisés complets du pipeline documentaire, du contrôle des fichiers et des vues.
"""

import io
from pathlib import Path
from datetime import timedelta
from django.test import TestCase, Client, override_settings
from django.utils import timezone
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from pypdf import PdfWriter
from PIL import Image

from vigilance_core.models import Company, DocumentRequirement, UploadRequest, SubmittedDocument
from vigilance_core.services.validator import (
    validate_file_technical_integrity,
    detect_real_mime_type,
    sanitize_filename,
    TechnicalValidationError
)
from vigilance_core.services.extractor import extract_document_text, find_business_patterns
from vigilance_core.services.pipeline import DocumentProcessingPipeline


def create_minimal_pdf_bytes(text_content: str = "Attestation de vigilance Urssaf pour SIREN 123456789 délivrée le 15/10/2026") -> bytes:
    """Génère un flux binaire PDF valide avec une page et du texte pour les tests."""
    writer = PdfWriter()
    # Ajoute une page blanche avec métadonnées
    writer.add_blank_page(width=200, height=200)
    # pypdf ne permet pas d'écrire facilement du texte directement sans font,
    # mais on peut injecter un flux standard PDF avec stream de texte
    buffer = io.BytesIO()
    # Écriture d'un PDF minimaliste standard avec stream de texte
    minimal_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
        b"2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n"
        b"3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
        b"4 0 obj <</Length 110>> stream\n"
        b"BT\n"
        b"/F1 12 Tf\n"
        b"50 250 Td\n"
        b"(Attestation Urssaf SIREN 123456789 date 15/10/2026 code SECU9876) Tj\n"
        b"ET\n"
        b"endstream\nendobj\n"
        b"5 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000244 00000 n \n0000000406 00000 n \n"
        b"trailer <</Size 6 /Root 1 0 R>>\nstartxref\n481\n%%EOF"
    )
    return minimal_pdf


def create_minimal_png_bytes() -> bytes:
    """Génère un flux binaire PNG valide de 10x10 pixels."""
    img = Image.new('RGB', (10, 10), color='blue')
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()


class TechnicalValidationTests(TestCase):
    def test_detect_real_mime_type(self):
        pdf_bytes = create_minimal_pdf_bytes()
        png_bytes = create_minimal_png_bytes()
        fake_bytes = b"Ceci est un faux fichier texte masquer en PDF"

        self.assertEqual(detect_real_mime_type(pdf_bytes), 'application/pdf')
        self.assertEqual(detect_real_mime_type(png_bytes), 'image/png')
        self.assertNotEqual(detect_real_mime_type(fake_bytes), 'application/pdf')

    def test_valid_pdf_integrity(self):
        pdf_bytes = create_minimal_pdf_bytes()
        uploaded_file = SimpleUploadedFile("attestation.pdf", pdf_bytes, content_type="application/pdf")
        results = validate_file_technical_integrity(uploaded_file)
        self.assertEqual(results['detected_mime'], 'application/pdf')
        self.assertGreaterEqual(results['num_pages'], 1)

    def test_valid_png_integrity(self):
        png_bytes = create_minimal_png_bytes()
        uploaded_file = SimpleUploadedFile("kbis.png", png_bytes, content_type="image/png")
        results = validate_file_technical_integrity(uploaded_file)
        self.assertEqual(results['detected_mime'], 'image/png')
        self.assertEqual(results['image_width'], 10)

    def test_reject_empty_file(self):
        uploaded_file = SimpleUploadedFile("vide.pdf", b"", content_type="application/pdf")
        with self.assertRaises(TechnicalValidationError) as cm:
            validate_file_technical_integrity(uploaded_file)
        self.assertEqual(cm.exception.code, "EMPTY_FILE")

    def test_reject_oversized_file(self):
        pdf_bytes = create_minimal_pdf_bytes()
        uploaded_file = SimpleUploadedFile("trop_grand.pdf", pdf_bytes, content_type="application/pdf")
        with self.assertRaises(TechnicalValidationError) as cm:
            # Limite artificielle à 50 octets
            validate_file_technical_integrity(uploaded_file, max_size_bytes=50)
        self.assertEqual(cm.exception.code, "FILE_TOO_LARGE")

    def test_reject_disguised_file(self):
        # Fichier texte déguisé avec une extension .pdf
        fake_content = b"echo 'malicious script'"
        uploaded_file = SimpleUploadedFile("fake.pdf", fake_content, content_type="application/pdf")
        with self.assertRaises(TechnicalValidationError) as cm:
            validate_file_technical_integrity(uploaded_file)
        self.assertEqual(cm.exception.code, "MIME_TYPE_MISMATCH")

    def test_reject_corrupted_pdf(self):
        corrupted = b"%PDF-1.4\ncorrupted content without valid xref or objects"
        uploaded_file = SimpleUploadedFile("corrupted.pdf", corrupted, content_type="application/pdf")
        with self.assertRaises(TechnicalValidationError) as cm:
            validate_file_technical_integrity(uploaded_file)
        self.assertIn("corrompu", cm.exception.message)


class ExtractionAndPatternsTests(TestCase):
    def test_business_patterns_detection(self):
        sample_text = "Entreprise Dupont SIREN 987654321, enregistrée le 24/09/2026, vérification CODE12345XYZ"
        patterns = find_business_patterns(sample_text)
        self.assertIn("987654321", patterns['siren_candidates'])
        self.assertIn("24/09/2026", patterns['date_candidates'])


@override_settings(STORAGE_BACKEND='local_archive')
class PipelineEndToEndTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Alpha Corp",
            siren="112233445",
            contact_name="Jean",
            contact_email="jean@alpha.test"
        )
        self.requirement = DocumentRequirement.objects.create(
            name="Attestation Urssaf",
            code="URSSAF",
            is_mandatory=True
        )
        self.upload_request = UploadRequest.create_for_company(self.company)

    def test_successful_pipeline_execution(self):
        pdf_bytes = create_minimal_pdf_bytes()
        uploaded_file = SimpleUploadedFile("mon_attestation.pdf", pdf_bytes, content_type="application/pdf")

        doc = DocumentProcessingPipeline.process_upload(
            uploaded_file=uploaded_file,
            company=self.company,
            requirement=self.requirement,
            upload_request=self.upload_request
        )

        self.assertEqual(doc.status, SubmittedDocument.Status.ARCHIVE_DRIVE)
        self.assertEqual(doc.detected_mime_type, 'application/pdf')
        self.assertTrue(doc.local_archive_path)
        self.assertIsNotNone(doc.archived_at)
        self.assertEqual(doc.error_message, "")

    def test_pipeline_catches_invalid_file(self):
        fake_file = SimpleUploadedFile("bad.pdf", b"Not a real PDF", content_type="application/pdf")
        with self.assertRaises(TechnicalValidationError):
            DocumentProcessingPipeline.process_upload(
                uploaded_file=fake_file,
                company=self.company,
                requirement=self.requirement,
                upload_request=self.upload_request
            )

        # L'enregistrement en base doit conserver le statut d'erreur pour traçabilité
        failed_doc = SubmittedDocument.objects.filter(company=self.company, status=SubmittedDocument.Status.ERREUR).first()
        self.assertIsNotNone(failed_doc)
        self.assertIn("MIME_TYPE_MISMATCH", str(failed_doc.technical_check_results))


@override_settings(STORAGE_BACKEND='local_archive')
class ViewsSecurityAndFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.company = Company.objects.create(
            name="Beta Logistique",
            siren="556677889",
            contact_name="Sophie",
            contact_email="sophie@beta.test"
        )
        self.requirement = DocumentRequirement.objects.create(
            name="Extrait Kbis",
            code="KBIS",
            is_mandatory=True
        )
        self.upload_request = UploadRequest.create_for_company(self.company, days_valid=10)

        # Utilisateur staff pour le dashboard
        self.user_model = get_user_model()
        self.admin_user = self.user_model.objects.create_superuser(
            username="admin_test",
            email="admin@test.fr",
            password="password123"
        )

    def test_public_deposit_valid_token(self):
        url = reverse('public_deposit', kwargs={'token': self.upload_request.token})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Beta Logistique")
        self.assertContains(response, "Extrait Kbis")

    def test_public_deposit_expired_token(self):
        self.upload_request.expires_at = timezone.now() - timedelta(days=1)
        self.upload_request.save()

        url = reverse('public_deposit', kwargs={'token': self.upload_request.token})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Ce lien a expiré", status_code=403)

    def test_public_deposit_revoked_token(self):
        self.upload_request.revoke(reason="Test de révocation")

        url = reverse('public_deposit', kwargs={'token': self.upload_request.token})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Ce lien a été révoqué", status_code=403)

    def test_public_deposit_invalid_token_404(self):
        url = reverse('public_deposit', kwargs={'token': 'jeton-totalement-inexistant'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_upload_flow_post_success(self):
        url = reverse('public_deposit', kwargs={'token': self.upload_request.token})
        pdf_bytes = create_minimal_pdf_bytes()
        upload_file = SimpleUploadedFile("kbis_officiel.pdf", pdf_bytes, content_type="application/pdf")

        response = self.client.post(url, {
            'requirement_id': self.requirement.id,
            'document_file': upload_file,
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "document(s) validé(s) et archivé(s) avec succès")
        self.assertEqual(SubmittedDocument.objects.filter(company=self.company).count(), 1)

    def test_upload_batch_multiple_files_success(self):
        req2 = DocumentRequirement.objects.create(name="RC Pro", code="RC_PRO", is_mandatory=True)
        url = reverse('public_deposit', kwargs={'token': self.upload_request.token})
        pdf_bytes = create_minimal_pdf_bytes()
        png_bytes = create_minimal_png_bytes()

        file1 = SimpleUploadedFile("kbis.pdf", pdf_bytes, content_type="application/pdf")
        file2 = SimpleUploadedFile("assurance.png", png_bytes, content_type="image/png")

        response = self.client.post(url, {
            f'file_{self.requirement.id}': file1,
            f'file_{req2.id}': file2,
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2 document(s) validé(s) et archivé(s) avec succès")
        self.assertEqual(SubmittedDocument.objects.filter(company=self.company).count(), 2)

    def test_admin_dashboard_access_control(self):
        url = reverse('admin_dashboard')

        # Non connecté -> redirection login
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        # Connecté en admin -> 200 OK
        self.client.force_login(self.admin_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tableau de Bord")
        self.assertContains(response, "Beta Logistique")
