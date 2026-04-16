import os
import ssl as _ssl

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN: str = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID: int = int(os.environ["TELEGRAM_CHAT_ID"])

AIRTABLE_API_KEY: str = os.environ["AIRTABLE_API_KEY"]
AIRTABLE_BASE_ID: str = os.environ["AIRTABLE_BASE_ID"]
AIRTABLE_TABLE_ID: str = os.environ["AIRTABLE_TABLE_ID"]
AIRTABLE_VIEW_NAME: str = os.environ.get("AIRTABLE_VIEW_NAME", "sys_ch_domains")
AIRTABLE_FIELD_NAME: str = os.environ.get("AIRTABLE_FIELD_NAME", "agency_domain_for_adspect")


def _ssl_ctx() -> _ssl.SSLContext:
    ctx = _ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = _ssl.CERT_NONE
    return ctx


DB_CONFIG: dict = dict(
    host=os.environ["DB_HOST"],
    port=int(os.environ.get("DB_PORT", "25060")),
    database=os.environ["DB_NAME"],
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    ssl=_ssl_ctx() if os.environ.get("DB_SSLMODE") == "require" else False,
)

CHECK_INTERVAL: int = int(os.environ.get("CHECK_INTERVAL_SECONDS", "60"))
CHANGE_INTERVAL: int = int(os.environ.get("CHANGE_INTERVAL_SECONDS", "3600"))
COOLDOWN_CHECKS: int = int(os.environ.get("COOLDOWN_CHECKS", "5"))
CHECK_TIMEOUT: int = int(os.environ.get("CHECK_TIMEOUT_SECONDS", "10"))
CHECK_RETRIES: int = int(os.environ.get("CHECK_RETRIES", "3"))

# Proxy checker
PROXY_AIRTABLE_BASE_ID: str = os.environ.get("PROXY_AIRTABLE_BASE_ID", "app0kK7fZvuE1lGvH")
PROXY_AIRTABLE_TABLE_ID: str = os.environ.get("PROXY_AIRTABLE_TABLE_ID", "tblCkvfN8PsSMKD46")
PROXY_AIRTABLE_VIEW: str = os.environ.get("PROXY_AIRTABLE_VIEW", "viwItY0XqTwjbs8JQ")
PROXY_CHECK_INTERVAL: int = int(os.environ.get("PROXY_CHECK_INTERVAL_SECONDS", "600"))
PROXY_CHECK_TIMEOUT: int = int(os.environ.get("PROXY_CHECK_TIMEOUT_SECONDS", "15"))
PROXY_CHECK_RETRIES: int = int(os.environ.get("PROXY_CHECK_RETRIES", "3"))
PROXY_EXPIRY_WARN_DAYS: int = int(os.environ.get("PROXY_EXPIRY_WARN_DAYS", "3"))
