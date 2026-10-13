"""
Service de stockage et d'archivage des documents.
Supporte le mode Google Drive API officiel (avec Service Account)
et un mode d'archivage local sécurisé pour le développement sans dépendance réseau externe.
Garantit la stricte confidentialité des fichiers (aucun accès public).
"""

import os
import shutil
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from django.conf import settings
from django.utils.text import slugify

logger = logging.getLogger(__name__)


@dataclass
class StorageResult:
    success: bool
    backend: str
    file_id: str
    folder_id: str
    local_path: str = ""
    error_message: str = ""


class LocalArchiveStorage:
    """
    Simulateur de stockage sécurisé local.
    Reproduit l'arborescence Google Drive : [Dossier Racine] / [Entreprise_SIREN] / [Type_Doc] / [Fichier].
    """
    def __init__(self, root_dir: Path = None):
        self.root_dir = root_dir or settings.LOCAL_ARCHIVE_DIR
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def archive(self, temp_file_path: Path, company_name: str, siren: str,
                requirement_code: str, normalized_filename: str, mime_type: str = "application/pdf") -> StorageResult:
        try:
            # 1. Dossier entreprise
            company_folder_name = slugify(f"{company_name}_{siren or 'sans-siren'}")
            # 2. Sous-dossier type de document
            req_folder_name = slugify(requirement_code)
            
            target_dir = self.root_dir / company_folder_name / req_folder_name
            target_dir.mkdir(parents=True, exist_ok=True)

            target_path = target_dir / normalized_filename

            # Copie du fichier temporaire vers l'archive
            shutil.copy2(str(temp_file_path), str(target_path))

            # Suppression du fichier temporaire
            if temp_file_path.exists():
                temp_file_path.unlink()

            rel_path = str(target_path.relative_to(settings.BASE_DIR))
            folder_rel = str(target_dir.relative_to(settings.BASE_DIR))

            return StorageResult(
                success=True,
                backend="local_archive",
                file_id=rel_path,
                folder_id=folder_rel,
                local_path=rel_path
            )
        except Exception as e:
            logger.error(f"Erreur lors de l'archivage local de {temp_file_path.name}: {e}")
            return StorageResult(
                success=False,
                backend="local_archive",
                file_id="",
                folder_id="",
                error_message=str(e)
            )


class GoogleDriveStorage:
    """
    Connecteur officiel Google Drive API v3 utilisant un compte de service (Service Account).
    Structure : Dossier Racine Configuré / [Entreprise (SIREN)] / [Type_Document] / [Fichier]
    """
    SCOPES = ['https://www.googleapis.com/auth/drive']

    def __init__(self):
        self.credentials_file = Path(settings.GOOGLE_SERVICE_ACCOUNT_FILE)
        if not self.credentials_file.is_absolute():
            self.credentials_file = settings.BASE_DIR / self.credentials_file
        self.root_folder_id = settings.GOOGLE_DRIVE_ROOT_FOLDER_ID
        self._service = None

    def _get_service(self):
        """Initialise paresseusement le client Google Drive API v3 (OAuth utilisateur ou Service Account)."""
        if self._service is None:
            if not self.root_folder_id:
                raise ValueError("GOOGLE_DRIVE_ROOT_FOLDER_ID n'est pas configuré dans les variables d'environnement.")

            from googleapiclient.discovery import build

            # 1. Vérification si un jeton OAuth utilisateur existe (pour compte personnel @gmail.com)
            token_path = getattr(settings, 'BASE_DIR', Path('.')) / getattr(settings, 'GOOGLE_OAUTH_TOKEN_FILE', 'token.json')
            if token_path.exists():
                try:
                    from google.oauth2.credentials import Credentials
                    from google.auth.transport.requests import Request
                    creds = Credentials.from_authorized_user_file(str(token_path), scopes=self.SCOPES)
                    if creds.expired and creds.refresh_token:
                        creds.refresh(Request())
                        with open(token_path, 'w') as f:
                            f.write(creds.to_json())
                    self._service = build('drive', 'v3', credentials=creds, cache_discovery=False)
                    return self._service
                except Exception as e:
                    logger.warning(f"Impossible d'utiliser token.json, tentative avec Service Account : {e}")

            # 2. Utilisation du compte de service (credentials.json)
            if not self.credentials_file.exists():
                raise FileNotFoundError(
                    f"Le fichier de clés Google Service Account est introuvable : {self.credentials_file}. "
                    "Veuillez placer votre credentials.json à la racine ou configurer GOOGLE_SERVICE_ACCOUNT_FILE."
                )

            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(
                str(self.credentials_file),
                scopes=self.SCOPES
            )
            self._service = build('drive', 'v3', credentials=creds, cache_discovery=False)
        return self._service

    def _find_or_create_subfolder(self, folder_name: str, parent_id: str) -> str:
        """Trouve un dossier existant ou le crée pour éviter les doublons."""
        service = self._get_service()
        # Échappement des apostrophes pour la requête Drive
        escaped_name = folder_name.replace("'", "\\'")
        query = f"'{parent_id}' in parents and name = '{escaped_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"

        response = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)',
            pageSize=1,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()

        files = response.get('files', [])
        if files:
            return files[0]['id']

        # Création du sous-dossier
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        folder = service.files().create(
            body=folder_metadata,
            fields='id',
            supportsAllDrives=True
        ).execute()

        return folder.get('id')

    def archive(self, temp_file_path: Path, company_name: str, siren: str,
                requirement_code: str, normalized_filename: str, mime_type: str = "application/pdf") -> StorageResult:
        try:
            from googleapiclient.http import MediaFileUpload

            service = self._get_service()

            # 1. Sous-dossier entreprise
            company_display = f"{company_name} ({siren})" if siren else company_name
            company_folder_id = self._find_or_create_subfolder(company_display, self.root_folder_id)

            # 2. Sous-dossier type de document
            req_folder_id = self._find_or_create_subfolder(requirement_code, company_folder_id)

            # 3. Métadonnées et envoi du fichier
            file_metadata = {
                'name': normalized_filename,
                'parents': [req_folder_id]
            }

            media = MediaFileUpload(
                str(temp_file_path),
                mimetype=mime_type,
                resumable=True
            )

            uploaded_file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name',
                supportsAllDrives=True
            ).execute()

            file_id = uploaded_file.get('id')

            # Nettoyage du fichier temporaire après succès
            if temp_file_path.exists():
                temp_file_path.unlink()

            return StorageResult(
                success=True,
                backend="google_drive",
                file_id=file_id,
                folder_id=req_folder_id
            )

        except Exception as e:
            error_str = str(e)
            logger.error(f"Erreur lors du transfert Google Drive de {temp_file_path.name}: {e}")

            # Détection explicite de la contrainte de quota des Service Accounts sur comptes personnels
            if "storageQuotaExceeded" in error_str or "do not have storage quota" in error_str:
                clean_msg = (
                    "Quota Google Drive : les comptes de service ont 0 Go de quota sur les comptes Google personnels (@gmail.com). "
                    "Le document a été sauvegardé en sécurité dans l'archive locale du serveur. "
                    "Pour activer l'envoi Drive sur votre compte personnel, lancez : python manage.py setup_google_oauth"
                )
            else:
                clean_msg = error_str

            # Sauvegarde de secours en archive locale pour ne JAMAIS perdre le fichier
            local_fallback = LocalArchiveStorage().archive(
                temp_file_path=temp_file_path,
                company_name=company_name,
                siren=siren,
                requirement_code=requirement_code,
                normalized_filename=normalized_filename,
                mime_type=mime_type
            )

            return StorageResult(
                success=False,
                backend="google_drive",
                file_id="",
                folder_id="",
                local_path=local_fallback.local_path if local_fallback.success else "",
                error_message=clean_msg
            )


def get_storage_service():
    """
    Fabrique le service de stockage adapté selon la configuration active.
    Si Google Drive est configuré et disponible, utilise Google Drive.
    Sinon, bascule sur le stockage d'archive local sécurisé.
    """
    if settings.STORAGE_BACKEND == 'google_drive':
        creds_path = Path(settings.GOOGLE_SERVICE_ACCOUNT_FILE)
        if not creds_path.is_absolute():
            creds_path = settings.BASE_DIR / creds_path
        if creds_path.exists() and settings.GOOGLE_DRIVE_ROOT_FOLDER_ID:
            return GoogleDriveStorage()
        else:
            logger.warning("Configuration Google Drive incomplète. Utilisation de l'archivage local de secours.")
            return LocalArchiveStorage()
    return LocalArchiveStorage()
