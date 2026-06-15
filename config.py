"""Kullanıcı yapılandırması — dil, isim, şifre, mod, model, Binance API anahtarları.

config.json'da saklanır (dosya izni 600). Şifre PBKDF2-SHA256 ile özetlenir,
düz metin olarak asla yazılmaz. Binance secret'ı yereldeki config.json'da
durur; dosyayı paylaşma.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"
ENV_FILE    = Path(__file__).parent / ".env"
PBKDF2_ITERS = 200_000
MIN_PW_LEN = 4


def _load_env() -> dict[str, str]:
    """`.env` dosyasından anahtar=değer çiftlerini oku."""
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


_ENV = _load_env()

# Seçilebilir Claude modelleri: anahtar → (model id, açıklama tr, açıklama en)
MODELS: dict[str, tuple[str | None, str, str]] = {
    "opus": ("claude-opus-4-8",
             "Claude Opus 4.8 — en güçlü analiz, daha yavaş/pahalı",
             "Claude Opus 4.8 — strongest analysis, slower"),
    "sonnet": ("claude-sonnet-4-6",
               "Claude Sonnet 4.6 — hız/zekâ dengesi (önerilen)",
               "Claude Sonnet 4.6 — best speed/intelligence balance (recommended)"),
    "haiku": ("claude-haiku-4-5",
              "Claude Haiku 4.5 — en hızlı, hafif analizler",
              "Claude Haiku 4.5 — fastest, light analysis"),
    "varsayilan": (None,
                   "Claude CLI varsayılan modeli",
                   "Claude CLI default model"),
}
DEFAULT_MODEL = "sonnet"


@dataclass
class Config:
    language: str = "tr"              # tr | en
    name: str = ""
    pw_salt: str = ""                 # hex
    pw_hash: str = ""                 # hex (PBKDF2-SHA256)
    mode: str = "standart"            # modes.MODES anahtarı (manuel işlemler için)
    model: str = DEFAULT_MODEL        # MODELS anahtarı
    binance_key: str = ""
    binance_secret: str = ""
    autonomous_mode: str = "dengeli"     # otonom risk profili: guvenli/dengeli/agresif
    trade_plan: str = "dengeli"          # sadece_long | dengeli | tam (manuel /tara için)
    otonom_trade_type: str = "long"      # long|short|longshort|scalp|kaldirac|tam
    leverage_enabled: bool = False       # kaldıraçlı paper öneriler (varsayılan kapalı)
    scalp_enabled: bool = False          # scalp paper modu (varsayılan kapalı)
    custom_max_positions: int = 0      # 0 = profil varsayılanı kullan
    custom_max_daily_trades: int = 0   # 0 = profil varsayılanı kullan
    custom_loss_streak: int = 0        # 0 = profil varsayılanı kullan
    custom_daily_loss_pct: float = 0.0 # 0.0 = profil varsayılanı kullan
    theme: str = "cyber"               # cyber | minimal | matrix | amber
    trading_mode: str = "paper"        # "paper" | "live" — gerçek emir gönderme modu
    live_autonomous: bool = False      # otonom mod da gerçek emir göndersin

    # ---- Borsa ----
    exchange: str = "binance"          # binance | bybit | okx
    bybit_key: str = ""
    bybit_secret: str = ""
    okx_key: str = ""
    okx_secret: str = ""
    okx_passphrase: str = ""

    # ---- Bildirimler ----
    telegram_token: str = ""
    telegram_chat_id: str = ""

    # ---- Strateji ----
    active_strategy: str = "konsensüs"  # momentum | dönüş | kırılım | konsensüs

    # ---- AI sağlayıcı ----
    ai_provider: str = "claude"        # claude | openai | gemini | ollama | grok
    openai_api_key: str = ""
    gemini_api_key: str = ""
    grok_api_key: str = ""
    openai_model: str = "gpt-4o"
    gemini_model: str = "gemini-2.0-flash"
    grok_model: str = "grok-3-mini"
    ollama_model: str = "llama3.2"

    # ---- şifre ----
    @staticmethod
    def _hash(password: str, salt_hex: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), PBKDF2_ITERS
        ).hex()

    def set_password(self, password: str) -> None:
        self.pw_salt = secrets.token_hex(16)
        self.pw_hash = self._hash(password, self.pw_salt)

    def verify_password(self, password: str) -> bool:
        if not self.pw_hash:
            return False
        return secrets.compare_digest(self.pw_hash, self._hash(password, self.pw_salt))

    # ---- model ----
    @property
    def model_id(self) -> str | None:
        return MODELS.get(self.model, MODELS[DEFAULT_MODEL])[0]

    # ---- kalıcılık ----
    def save(self) -> None:
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))
        os.chmod(CONFIG_FILE, 0o600)

    @classmethod
    def load(cls) -> "Config":
        d = json.loads(CONFIG_FILE.read_text())
        obj = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        # .env dosyası varsa API key'leri ortam değişkeninden al (öncelikli)
        if _ENV.get("ANTHROPIC_API_KEY"):
            pass  # Claude SDK kendi ortam değişkenini okur
        if _ENV.get("OPENAI_API_KEY") and not obj.openai_api_key:
            obj.openai_api_key = _ENV["OPENAI_API_KEY"]
        if _ENV.get("GEMINI_API_KEY") and not obj.gemini_api_key:
            obj.gemini_api_key = _ENV["GEMINI_API_KEY"]
        if _ENV.get("GROK_API_KEY") and not obj.grok_api_key:
            obj.grok_api_key = _ENV["GROK_API_KEY"]
        if _ENV.get("BINANCE_API_KEY") and not obj.binance_key:
            obj.binance_key = _ENV["BINANCE_API_KEY"]
        if _ENV.get("BINANCE_SECRET") and not obj.binance_secret:
            obj.binance_secret = _ENV["BINANCE_SECRET"]
        if _ENV.get("TELEGRAM_TOKEN") and not obj.telegram_token:
            obj.telegram_token = _ENV["TELEGRAM_TOKEN"]
        if _ENV.get("TELEGRAM_CHAT_ID") and not obj.telegram_chat_id:
            obj.telegram_chat_id = _ENV["TELEGRAM_CHAT_ID"]
        return obj

    @staticmethod
    def exists() -> bool:
        return CONFIG_FILE.exists()


# Aktif yapılandırma — app.py açılışta atar; ai.py model/mod için okur.
CURRENT: Config | None = None


def current() -> Config:
    global CURRENT
    if CURRENT is None:
        CURRENT = Config.load() if Config.exists() else Config()
    return CURRENT


def set_current(cfg: Config) -> None:
    global CURRENT
    CURRENT = cfg
