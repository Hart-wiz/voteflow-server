"""
Django settings for VoteFlow project.

Environment variables are loaded from .env via python-decouple.
Authentication powered by django-ninja-jwt.
"""

import re
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from decouple import config

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = (
    ["*"]
    if DEBUG
    else config(
        "ALLOWED_HOSTS",
        default="",
        cast=lambda v: [h.strip() for h in v.split(",") if h.strip()],
    )
)

# ---------------------------------------------------------------------------
# Installed Apps
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "ninja_extra",
    "ninja_jwt",
    "ninja_jwt.token_blacklist",  # Needed for refresh token blacklisting
    "corsheaders",
    "django_filters",
    "cloudinary_storage",
    "cloudinary",
    # Local apps
    "accounts",
    "polls",
    "voting",
    "payments",
    "notifications",
]

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "ninja.compatibility.files.fix_request_files_middleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.middleware.RateLimitMiddleware",
    "config.middleware.ErrorHandlingMiddleware",
    "config.middleware.LegacyPollDeprecationMiddleware",
]

# ---------------------------------------------------------------------------
# URL Configuration
# ---------------------------------------------------------------------------
ROOT_URLCONF = "config.urls"

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Database (PostgreSQL via psycopg v3)
# ---------------------------------------------------------------------------
DB_ENGINE = config("DB_ENGINE", default="django.db.backends.postgresql")
if DB_ENGINE == "django.db.backends.sqlite3":
    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": config("DB_NAME", default=str(BASE_DIR / "db.sqlite3")),
            "OPTIONS": {"timeout": 20},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": config("DB_NAME", default="voteflow"),
            "USER": config("DB_USER", default="postgres"),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": config("DB_HOST", default="localhost"),
            "PORT": config("DB_PORT", default="5432"),
            # Supabase requires TLS. Local PostgreSQL can keep libpq's default
            # behavior by leaving DB_SSLMODE at "prefer".
            "OPTIONS": {"sslmode": config("DB_SSLMODE", default="prefer")},
        }
    }

# ---------------------------------------------------------------------------
# Password Validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Custom User Model
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

# ---------------------------------------------------------------------------
# Ninja JWT
# ---------------------------------------------------------------------------
NINJA_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:3000").rstrip("/")
CLOUDFLARE_PAGES_DOMAIN = config(
    "CLOUDFLARE_PAGES_DOMAIN", default="voteflow-client.pages.dev"
).strip().lower()
CLOUDFLARE_PAGES_ORIGIN = f"https://{CLOUDFLARE_PAGES_DOMAIN}"

# Allow the configured client origin plus the project's production Pages URL.
# Cloudflare preview deployments use a subdomain of the project pages.dev host.
CORS_ALLOWED_ORIGINS = list(dict.fromkeys([FRONTEND_URL, CLOUDFLARE_PAGES_ORIGIN]))
CORS_ALLOWED_ORIGIN_REGEXES = [
    rf"^https://(?:[a-z0-9-]+\.)?{re.escape(CLOUDFLARE_PAGES_DOMAIN)}$",
]
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = list(
    dict.fromkeys(
        [
            FRONTEND_URL,
            CLOUDFLARE_PAGES_ORIGIN,
            f"https://*.{CLOUDFLARE_PAGES_DOMAIN}",
        ]
    )
)

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & Media Files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Cloudinary configuration
CLOUDINARY_STORAGE = {
    "CLOUD_NAME": config("CLOUDINARY_CLOUD_NAME", default=""),
    "API_KEY": config("CLOUDINARY_API_KEY", default=""),
    "API_SECRET": config("CLOUDINARY_API_SECRET", default=""),
}

STORAGES = {
    "default": {
        "BACKEND": (
            "cloudinary_storage.storage.MediaCloudinaryStorage"
            if CLOUDINARY_STORAGE["CLOUD_NAME"]
            else "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# ---------------------------------------------------------------------------
# Paystack
# ---------------------------------------------------------------------------
PAYSTACK_SECRET_KEY = config("PAYSTACK_SECRET_KEY", default="")
PAYSTACK_PUBLIC_KEY = config("PAYSTACK_PUBLIC_KEY", default="")

# Dragonfly speaks the Redis protocol used by Django's cache and Celery.
DRAGONFLY_URL = config("DRAGONFLY_URL", default="")
if DRAGONFLY_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": DRAGONFLY_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "voteflow-local",
        }
    }

CELERY_BROKER_URL = config(
    "CELERY_BROKER_URL", default=DRAGONFLY_URL or "redis://localhost:6379/0"
)
CELERY_RESULT_BACKEND = config(
    "CELERY_RESULT_BACKEND", default=DRAGONFLY_URL or CELERY_BROKER_URL
)
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULE = {
    "expire-vote-attempts-every-five-minutes": {
        "task": "voting.tasks.check_vote_attempt_expiration",
        "schedule": 300.0,
    },
    "close-ended-contests-every-minute": {
        "task": "polls.tasks.close_ended_contests",
        "schedule": 60.0,
    },
    "detect-suspicious-voting-every-two-minutes": {
        "task": "voting.tasks.detect_suspicious_patterns",
        "schedule": 120.0,
    },
}
API_SUNSET_AT = datetime.fromisoformat(
    config("API_SUNSET_AT", default=(datetime.now(dt_timezone.utc) + timedelta(days=30)).date().isoformat() + "T00:00:00+00:00")
)

# ---------------------------------------------------------------------------
# Platform Fee (percentage taken from paid votes)
# ---------------------------------------------------------------------------
PLATFORM_FEE_PERCENT = 20


# For development (Prints emails directly to the console instead of sending them)
# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# using production mode for now


# ---------------------------------------------------------------------------
# Transactional Email (Resend)
# ---------------------------------------------------------------------------
RESEND_API_KEY = config("RESEND_API_KEY", default="")
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default="VoteFlow <onboarding@resend.dev>"
)

# Optional identity gateway for phone, NIN, voter's card, and biometric checks.
IDENTITY_PROVIDER_URL = config("IDENTITY_PROVIDER_URL", default="")
IDENTITY_PROVIDER_API_KEY = config("IDENTITY_PROVIDER_API_KEY", default="")
