from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Core
    openai_api_key: str

    # Supabase Postgres
    # Session mode pooler URL with asyncpg driver (for SQLAlchemy)
    database_url: str = "postgresql+asyncpg://postgres.xxx:password@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"
    # Direct connection URL with psycopg driver (for LangGraph checkpointer)
    database_url_direct: str = "postgresql://postgres.xxx:password@db.xxx.supabase.co:5432/postgres"

    # Public API base URL (used to generate OAuth links sent to users)
    api_base_url: str = "https://41ac-149-88-106-148.ngrok-free.app"

    # WhatsApp
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = "aura-verify-token"
    whatsapp_business_account_id: str = ""  # WABA ID for template management

    # Canvas
    canvas_base_url: str = ""
    canvas_client_id: str = ""
    canvas_client_secret: str = ""

    # Google OAuth (legacy — kept for migration, Composio handles OAuth now)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""

    # Composio (manages OAuth & API calls for Gmail + Calendar)
    composio_api_key: str = ""
    composio_gmail_auth_config_id: str = ""      # Auth config for Gmail
    composio_gcal_auth_config_id: str = ""       # Auth config for Google Calendar
    composio_outlook_auth_config_id: str = ""    # Auth config for Microsoft Outlook (email + calendar)

    # Transcription
    deepgram_api_key: str = ""

    # File Storage (Cloudflare R2 / S3)
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "aura-voice-notes"
    r2_endpoint_url: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
