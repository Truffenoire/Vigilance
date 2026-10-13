"""
Service d'extraction de texte (natif PDF et OCR optionnel).
Conserve le fichier d'origine sans modification et enregistre le texte séparément.
Prépare la détection des motifs (SIREN, dates, codes de sécurité) pour les évolutions futures.
"""

import io
import re
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from pypdf import PdfReader
from PIL import Image

logger = logging.getLogger(__name__)

# Vérification de la disponibilité de Tesseract OCR
TESSERACT_AVAILABLE = False
try:
    import pytesseract
    # Vérifie si la commande tesseract existe dans l'environnement
    if shutil.which("tesseract"):
        TESSERACT_AVAILABLE = True
except Exception:
    TESSERACT_AVAILABLE = False


def find_business_patterns(text: str) -> Dict[str, Any]:
    """
    Recherche des motifs métiers courants (SIREN, dates, codes de vérification)
    à titre purement informatif. Ne constitue en aucun cas une validation juridique.
    """
    patterns = {
        'siren_candidates': [],
        'date_candidates': [],
        'security_code_candidates': [],
    }
    if not text:
        return patterns

    # Recherche des suites de 9 chiffres (candidats SIREN)
    siren_matches = re.findall(r'\b\d{9}\b', text)
    patterns['siren_candidates'] = list(set(siren_matches))[:5]

    # Recherche des dates au format français JJ/MM/AAAA ou JJ-MM-AAAA
    date_matches = re.findall(r'\b(0[1-9]|[12][0-9]|3[01])[-/.](0[1-9]|1[012])[-/.](20\d\d)\b', text)
    patterns['date_candidates'] = [f"{m[0]}/{m[1]}/{m[2]}" for m in date_matches][:5]

    # Recherche de codes de sécurité (lettres et chiffres de 6 à 16 caractères, ex: Urssaf / Impôts)
    code_matches = re.findall(r'\b[A-Z0-9]{8,14}\b', text)
    # Filtrer les mots courants
    patterns['security_code_candidates'] = [c for c in set(code_matches) if any(ch.isdigit() for ch in c) and any(ch.isalpha() for ch in c)][:3]

    return patterns


def extract_text_from_pdf(file_path: Path) -> Dict[str, Any]:
    """
    Extrait le texte natif d'un fichier PDF avec pypdf.
    """
    extracted_pages = []
    total_chars = 0

    try:
        reader = PdfReader(str(file_path))
        for page_idx, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            page_text = page_text.strip()
            if page_text:
                extracted_pages.append(f"--- Page {page_idx + 1} ---\n{page_text}")
                total_chars += len(page_text)
    except Exception as e:
        logger.warning(f"Erreur lors de la lecture native du PDF {file_path.name}: {e}")
        return {
            'text': "",
            'char_count': 0,
            'has_usable_text': False,
            'method': "pypdf_error",
            'error': str(e),
            'patterns': {}
        }

    full_text = "\n\n".join(extracted_pages).strip()
    has_usable = total_chars >= 30  # Au moins 30 caractères signifiants

    return {
        'text': full_text,
        'char_count': total_chars,
        'has_usable_text': has_usable,
        'method': "pypdf_native",
        'patterns': find_business_patterns(full_text)
    }


def extract_text_from_image(file_path: Path) -> Dict[str, Any]:
    """
    Tente l'extraction de texte par OCR sur une image si Tesseract est disponible.
    """
    if not TESSERACT_AVAILABLE:
        return {
            'text': "",
            'char_count': 0,
            'has_usable_text': False,
            'method': "ocr_not_installed",
            'note': "Tesseract OCR n'est pas installé sur le serveur hôte.",
            'patterns': {}
        }

    try:
        img = Image.open(str(file_path))
        text = pytesseract.image_to_string(img, lang='fra+eng').strip()
        char_count = len(text)
        has_usable = char_count >= 20
        return {
            'text': text,
            'char_count': char_count,
            'has_usable_text': has_usable,
            'method': "pytesseract_ocr",
            'patterns': find_business_patterns(text)
        }
    except Exception as e:
        logger.warning(f"Erreur OCR sur {file_path.name}: {e}")
        return {
            'text': "",
            'char_count': 0,
            'has_usable_text': False,
            'method': "ocr_error",
            'error': str(e),
            'patterns': {}
        }


def extract_document_text(file_path: Path, mime_type: str) -> Dict[str, Any]:
    """
    Point d'entrée principal pour l'extraction de texte selon le type de fichier.
    """
    if mime_type == 'application/pdf':
        res = extract_text_from_pdf(file_path)
        # Si le PDF ne contient aucun texte natif (document purement scanné sous forme d'image)
        # on signale l'absence de texte exploitable sans bloquer le pipeline
        return res
    elif mime_type in ('image/jpeg', 'image/png'):
        return extract_text_from_image(file_path)
    else:
        return {
            'text': "",
            'char_count': 0,
            'has_usable_text': False,
            'method': "unsupported_type",
            'patterns': {}
        }
