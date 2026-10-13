"""
Django settings for vigilance_project.
Plateforme de collecte et de contrôle documentaire.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url

# Chemin racine du projet
BASE_DIR = Path(__file__).resolve().parent.parent

# Chargement des variables d'environnement depuis .env
load_dotenv(BASE_DIR / '.env')

# Clé secrète (lue depuis .env, jamais codée en dur)
SECRET_KEY = os.getenv('SECRET_KEY', 'default-insecure-key-for-dev-only-32charmin')

# Mode débogage
DEBUG = os.getenv('DEBUG', 'True').strip().lower() in ('true', '1', 'yes')

# Hôtes autorisés
raw_allowed_hosts = os.environ.get(
    "ALLOWED_HOSTS",
    "localhost,127.0.0.1,web-production-31bcf2.up.railway.app",
)

ALLOWED_HOSTS = [
    host.strip()
    for host in raw_allowed_hosts.split(",")
    if host.strip()
]

# Autorisation des tunnels ngrok pour les démos (ne pas activer en production)
if DEBUG:
    ALLOWED_HOSTS += ['*.ngrok-free.app', '*.ngrok.io', '*.ngrok.app']
    CSRF_TRUSTED_ORIGINS = [
        'https://*.ngrok-free.app',
        'https://*.ngrok.io',
        'https://*.ngrok.app',
    ]

# Applications installées
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Application métier Vigilance
    'vigilance_core.apps.VigilanceCoreConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Fichiers statiques en production
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'vigilance_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'vigilance_project.wsgi.application'

# Base de données :
# Si DATABASE_URL est fourni (PostgreSQL), dj_database_url le configure.
# Sinon, fallback automatique sur SQLite3 pour démarrage immédiat sans friction.
database_url = os.getenv('DATABASE_URL', '').strip()
if database_url:
    DATABASES = {
        'default': dj_database_url.config(
            default=database_url,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Validation des mots de passe
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalisation & Fuseau horaire
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Europe/Paris'
USE_I18N = True
USE_TZ = True

# Fichiers statiques
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ==========================================
# PARAMÈTRES MÉTIER DE LA PLATEFORME
# ==========================================

# Limite de taille des uploads en Mo (par défaut 10 Mo)
MAX_UPLOAD_SIZE_MB = int(os.getenv('MAX_UPLOAD_SIZE_MB', '10'))
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024

# Sécurité Django sur la taille des requêtes entrantes
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE_BYTES + (1024 * 1024)
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE_BYTES + (1024 * 1024)

# Formats et types MIME autorisés (stricte vérification binaire)
ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
ALLOWED_MIME_TYPES = {
    'application/pdf',
    'image/jpeg',
    'image/png',
}

# Dossiers de stockage
TEMP_UPLOAD_DIR = BASE_DIR / os.getenv('TEMP_UPLOAD_DIR', 'storage/temp')
LOCAL_ARCHIVE_DIR = BASE_DIR / os.getenv('LOCAL_ARCHIVE_DIR', 'storage/archive')

# Création automatique des répertoires s'ils n'existent pas
TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
LOCAL_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

# Backend de stockage définitif : 'local_archive' ou 'google_drive'
STORAGE_BACKEND = os.getenv('STORAGE_BACKEND', 'local_archive')

# Google Drive API
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json')
GOOGLE_DRIVE_ROOT_FOLDER_ID = os.getenv('GOOGLE_DRIVE_ROOT_FOLDER_ID', '')
GOOGLE_OAUTH_TOKEN_FILE = os.getenv('GOOGLE_OAUTH_TOKEN_FILE', 'token.json')
GOOGLE_OAUTH_CLIENT_SECRETS_FILE = os.getenv('GOOGLE_OAUTH_CLIENT_SECRETS_FILE', 'client_secret.json')

# OCR Tesseract
TESSERACT_CMD = os.getenv('TESSERACT_CMD', '')

# Journalisation sécurisée (pas de fuite de tokens ou contenus dans les logs)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '[%(asctime)s] %(levelname)s in %(name)s: %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'loggers': {
        'vigilance_core': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
