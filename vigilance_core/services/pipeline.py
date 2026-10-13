"""
Coordinateur du pipeline de traitement documentaire.
Enchaîne :
1. Contrôles techniques stricts (taille, magic bytes, intégrité).
2. Zone temporaire sécurisée.
3. Extraction de texte & OCR.
4. Archivage dans Google Drive ou archive locale.
5. Traçabilité complète du document en base PostgreSQL / SQLite.
"""

import logging
from pathlib import Path
from django.conf import settings
from django.utils import timezone
from vigilance_core.models import Company, DocumentRequirement, UploadRequest, SubmittedDocument
from .validator import validate_file_technical_integrity, sanitize_filename, TechnicalValidationError
from .extractor import extract_document_text
from .storage import get_storage_service

logger = logging.getLogger(__name__)


class DocumentProcessingPipeline:
    @classmethod
    def process_upload(
        cls,
        uploaded_file,
        company: Company,
        requirement: DocumentRequirement,
        upload_request: UploadRequest = None
    ) -> SubmittedDocument:
        """
        Traite un fichier déposé de bout en bout et garantit la mise à jour du statut.
        """
        original_filename = uploaded_file.name
        file_size = uploaded_file.size
        normalized_filename = sanitize_filename(original_filename, company.name, requirement.code)

        # Création immédiate de l'enregistrement avec le statut initial RECU
        doc = SubmittedDocument.objects.create(
            company=company,
            requirement=requirement,
            upload_request=upload_request,
            original_filename=original_filename,
            normalized_filename=normalized_filename,
            file_size_bytes=file_size,
            detected_mime_type="unknown",
            status=SubmittedDocument.Status.RECU
        )

        temp_file_path = None
        try:
            # ==========================================
            # ÉTAPE 1 : CONTRÔLE TECHNIQUE
            # ==========================================
            check_results = validate_file_technical_integrity(uploaded_file)
            doc.detected_mime_type = check_results.get('detected_mime', 'application/octet-stream')
            doc.technical_check_results = check_results
            doc.status = SubmittedDocument.Status.FORMAT_VALIDE
            doc.save(update_fields=['detected_mime_type', 'technical_check_results', 'status'])

            # ==========================================
            # ÉTAPE 2 : ÉCRITURE TEMPORAIRE SÉCURISÉE
            # ==========================================
            temp_file_path = settings.TEMP_UPLOAD_DIR / normalized_filename
            uploaded_file.seek(0)
            with open(temp_file_path, 'wb') as temp_dest:
                for chunk in uploaded_file.chunks():
                    temp_dest.write(chunk)

            # ==========================================
            # ÉTAPE 3 : EXTRACTION DE TEXTE & ANALYSE
            # ==========================================
            extraction_result = extract_document_text(temp_file_path, doc.detected_mime_type)
            doc.extracted_text = extraction_result.get('text', '')
            doc.extracted_text_char_count = extraction_result.get('char_count', 0)
            doc.has_usable_text = extraction_result.get('has_usable_text', False)

            # Mise à jour des résultats techniques avec les détails d'extraction
            doc.technical_check_results['extraction'] = {
                'method': extraction_result.get('method'),
                'patterns': extraction_result.get('patterns', {})
            }

            if doc.has_usable_text:
                doc.status = SubmittedDocument.Status.TEXTE_EXTRAIT
            else:
                # Fichier valide techniquement mais sans texte extrait exploitable (ex: scan pur)
                doc.status = SubmittedDocument.Status.A_EXAMINER
            doc.save(update_fields=['extracted_text', 'extracted_text_char_count', 'has_usable_text', 'technical_check_results', 'status'])

            # ==========================================
            # ÉTAPE 4 : ARCHIVAGE DÉFINITIF
            # ==========================================
            storage_service = get_storage_service()
            storage_result = storage_service.archive(
                temp_file_path=temp_file_path,
                company_name=company.name,
                siren=company.siren,
                requirement_code=requirement.code,
                normalized_filename=normalized_filename,
                mime_type=doc.detected_mime_type
            )

            doc.storage_backend = storage_result.backend
            if storage_result.success:
                if storage_result.backend == 'google_drive':
                    doc.drive_file_id = storage_result.file_id
                    doc.drive_folder_id = storage_result.folder_id
                    doc.status = SubmittedDocument.Status.ARCHIVE_DRIVE
                else:
                    doc.local_archive_path = storage_result.local_path
                    doc.status = SubmittedDocument.Status.ARCHIVE_DRIVE

                doc.archived_at = timezone.now()
                doc.error_message = ""
            else:
                doc.status = SubmittedDocument.Status.ERREUR
                doc.local_archive_path = storage_result.local_path
                doc.error_message = f"Échec de l'archivage : {storage_result.error_message}"

            doc.save()
            return doc

        except TechnicalValidationError as te:
            doc.status = SubmittedDocument.Status.ERREUR
            doc.error_message = te.message
            doc.technical_check_results['validation_error'] = {
                'code': te.code,
                'details': te.details
            }
            doc.save()
            # Nettoyage si le temporaire a été créé
            if temp_file_path and temp_file_path.exists():
                try:
                    temp_file_path.unlink()
                except Exception:
                    pass
            raise

        except Exception as e:
            logger.exception(f"Erreur inattendue dans le pipeline pour {original_filename}")
            doc.status = SubmittedDocument.Status.ERREUR
            doc.error_message = f"Erreur interne de traitement : {str(e)}"
            doc.save()
            if temp_file_path and temp_file_path.exists():
                try:
                    temp_file_path.unlink()
                except Exception:
                    pass
            raise
