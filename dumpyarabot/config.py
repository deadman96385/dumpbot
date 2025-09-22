from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str

    JENKINS_URL: AnyHttpUrl
    JENKINS_USER_NAME: str
    JENKINS_USER_TOKEN: str

    SUDO_USERS: list[int] = []

    ALLOWED_CHATS: list[int] = []

    # Moderated request system configuration
    REQUEST_CHAT_ID: int = -1001234567890  # Configure actual chat ID
    REVIEW_CHAT_ID: int = -1001234567891  # Configure actual chat ID

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()

# Callback data prefixes
CALLBACK_ACCEPT = "accept_"
CALLBACK_REJECT = "reject_"
CALLBACK_TOGGLE_ALT = "toggle_alt_"
CALLBACK_TOGGLE_FORCE = "toggle_force_"
CALLBACK_TOGGLE_BLACKLIST = "toggle_blacklist_"
CALLBACK_TOGGLE_PRIVDUMP = "toggle_privdump_"
CALLBACK_SUBMIT_ACCEPTANCE = "submit_accept_"
