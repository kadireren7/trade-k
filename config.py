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
PBKDF2_ITERS = 200_000
MIN_PW_LEN = 4

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
    autonomous_mode: str = "dengeli"   # otonom risk profili: guvenli/dengeli/agresif
    trade_plan: str = "dengeli"        # sadece_long | dengeli | tam
    leverage_enabled: bool = False     # kaldıraçlı paper öneriler (varsayılan kapalı)
    scalp_enabled: bool = False        # scalp paper modu (varsayılan kapalı)
    custom_max_positions: int = 0      # 0 = profil varsayılanı kullan
    custom_max_daily_trades: int = 0   # 0 = profil varsayılanı kullan
    custom_loss_streak: int = 0        # 0 = profil varsayılanı kullan
    custom_daily_loss_pct: float = 0.0 # 0.0 = profil varsayılanı kullan
    theme: str = "cyber"               # cyber | minimal | matrix | amber

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
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

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
