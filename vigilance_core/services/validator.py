"""
Service de contrôle technique des fichiers déposés.
Vérifie la taille, la signature binaire (magic bytes), le type MIME réel
et l'intégrité structurelle (PDF / images) pour contrer les fichiers corrompus ou malveillants.
"""

import os
import io
import re
import secrets
from pathlib import Path
from typing import Tuple, Dict, Any, Optional
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify
import puremagic
import filetype
from pypdf import PdfReader
from PIL import Image, UnidentifiedImageError


class TechnicalValidationError(Exception):
    """Exception levée lorsqu'un fichier échoue aux contrôles techniques."""
    def __init__(self, message: str, code: str = "INVALID_FILE", details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


def sanitize_filename(original_name: str, company_name: str, requirement_code: str) -> str:
    """
    Génère un nom de fichier normalisé et sécurisé pour prévenir le path-traversal
    et éviter l'écrasement de fichiers antérieurs.
    Format : {YYYYMMDD_HHMMSS}_{CODE}_{SLUG_ENTREPRISE}_{JETON_8_CAR}.{ext}
    """
    ext = Path(original_name).suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        ext = '.pdf' if 'pdf' in ext else '.bin'

    clean_company = slugify(company_name)[:30] or "partenaire"
    clean_code = re.sub(r'[^A-Za-z0-9_]', '', requirement_code).upper()[:20]
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    random_suffix = secrets.token_hex(4)

    return f"{timestamp}_{clean_code}_{clean_company}_{random_suffix}{ext}"


def detect_real_mime_type(file_bytes: bytes) -> str:
    """
    Détecte le type MIME réel via l'analyse des magic bytes (signature binaire en tête de fichier).
    Ne se fie jamais à l'extension ni au Content-Type envoyé par le client HTTP.
    """
    # 1. Utilisation de filetype
    kind = filetype.guess(file_bytes[:2048])
    if kind is not None:
        return kind.mime

    # 2. Fallback avec puremagic
    try:
        matches = puremagic.magic_string(file_bytes[:2048])
        if matches:
            return matches[0].mime_type
    except Exception:
        pass

    # 3. Vérification manuelle des signatures fondamentales
    if file_bytes.startswith(b'%PDF-'):
        return 'application/pdf'
    if file_bytes.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if file_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'

    return 'application/octet-stream'


def validate_file_technical_integrity(file_obj, max_size_bytes: int = None) -> Dict[str, Any]:
    """
    Exécute la batterie de contrôles techniques sur un fichier uploadé Django (UploadedFile) ou flux binaire.
    Retourne un dictionnaire de résultats techniques en cas de succès,
    ou lève une TechnicalValidationError avec un message explicite en français.
    """
    if max_size_bytes is None:
        max_size_bytes = settings.MAX_UPLOAD_SIZE_BYTES

    original_filename = getattr(file_obj, 'name', 'fichier_inconnu')
    file_size = getattr(file_obj, 'size', 0)

    # 1. Contrôle : Fichier non vide
    if file_size <= 0:
        raise TechnicalValidationError(
            message="Le fichier transmis est vide (taille de 0 octet).",
            code="EMPTY_FILE"
        )

    # 2. Contrôle : Limite de taille
    if file_size > max_size_bytes:
        max_mb = max_size_bytes / (1024 * 1024)
        actual_mb = file_size / (1024 * 1024)
        raise TechnicalValidationError(
            message=f"Le fichier dépasse la taille maximale autorisée de {max_mb:.0f} Mo (taille actuelle : {actual_mb:.1f} Mo).",
            code="FILE_TOO_LARGE",
            details={'file_size': file_size, 'max_size': max_size_bytes}
        )

    # 3. Contrôle : Extension déclarée autorisée
    ext = Path(original_filename).suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        allowed_list = ", ".join(sorted(settings.ALLOWED_EXTENSIONS))
        raise TechnicalValidationError(
            message=f"Format de fichier non autorisé ({ext}). Les formats acceptés sont : {allowed_list}.",
            code="INVALID_EXTENSION",
            details={'extension': ext}
        )

    # Lecture des données (ou de la tête) pour analyse binaire
    # Pour un UploadedFile Django, on conserve la position
    file_obj.seek(0)
    file_bytes = file_obj.read()
    file_obj.seek(0)  # Rembobinage

    # 4. Contrôle : Signature binaire et type MIME réel
    detected_mime = detect_real_mime_type(file_bytes)
    if detected_mime not in settings.ALLOWED_MIME_TYPES:
        raise TechnicalValidationError(
            message=f"Le contenu réel du fichier ({detected_mime}) ne correspond pas à un format valide (PDF, JPEG ou PNG). Les fichiers déguisés ou exécutables sont strictement refusés.",
            code="MIME_TYPE_MISMATCH",
            details={'detected_mime': detected_mime, 'declared_extension': ext}
        )

    # Vérification de cohérence entre extension et type réel
    if detected_mime == 'application/pdf' and ext != '.pdf':
        raise TechnicalValidationError(
            message="Le fichier est un PDF mais porte une extension trompeuse.",
            code="EXTENSION_MISMATCH"
        )
    if detected_mime in ('image/jpeg', 'image/png') and ext not in ('.jpg', '.jpeg', '.png'):
        raise TechnicalValidationError(
            message="L'image porte une extension ne correspondant pas à son format réel.",
            code="EXTENSION_MISMATCH"
        )

    # 5. Contrôle : Décodage et intégrité structurelle
    inspection_details = {
        'detected_mime': detected_mime,
        'size_bytes': file_size,
        'declared_extension': ext,
    }

    if detected_mime == 'application/pdf':
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            # Test de lecture des pages
            num_pages = len(reader.pages)
            if num_pages == 0:
                raise TechnicalValidationError(
                    message="Le document PDF ne contient aucune page.",
                    code="EMPTY_PDF"
                )
            if reader.is_encrypted:
                # Tentative de déchiffrement sans mot de passe
                try:
                    reader.decrypt("")
                except Exception:
                    raise TechnicalValidationError(
                        message="Le fichier PDF est protégé par mot de passe. Veuillez fournir un fichier non chiffré.",
                        code="ENCRYPTED_PDF"
                    )
            inspection_details['num_pages'] = num_pages
        except TechnicalValidationError:
            raise
        except Exception as e:
            raise TechnicalValidationError(
                message="Le fichier PDF est endommagé ou corrompu et ne peut pas être lu.",
                code="CORRUPTED_PDF",
                details={'error': str(e)}
            )

    elif detected_mime in ('image/jpeg', 'image/png'):
        try:
            image = Image.open(io.BytesIO(file_bytes))
            image.verify()  # Vérifie l'intégrité sans charger tous les pixels
            # Réouverture pour lire les dimensions
            image = Image.open(io.BytesIO(file_bytes))
            inspection_details['image_width'] = image.width
            inspection_details['image_height'] = image.height
            inspection_details['image_format'] = image.format
        except Exception as e:
            raise TechnicalValidationError(
                message="L'image est endommagée et ne peut pas être décodée.",
                code="CORRUPTED_IMAGE",
                details={'error': str(e)}
            )

    return inspection_details
