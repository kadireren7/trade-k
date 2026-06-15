"""Secret hygiene testleri — token/key'lerin kaynak koda sızmaması."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

# Kaynak kod dosyaları (config.json hariç — o .gitignore'da)
SOURCE_FILES = [
    f for f in ROOT.glob("*.py")
    if f.name not in ("conftest.py",)
]
TEST_FILES = list((ROOT / "tests").glob("*.py"))
ALL_PY = SOURCE_FILES + TEST_FILES


# ── Gerçek token pattern'leri ────────────────────────────────────────────────

# Telegram bot token: <bot_id>:<random_string> formatı
TELEGRAM_TOKEN_RE = re.compile(r"\d{8,12}:[A-Za-z0-9_-]{35,}", re.ASCII)

# Çok kısa olmayan hex API key'leri (32+ karakter)
LONG_HEX_RE = re.compile(r"[0-9a-fA-F]{40,}")

# sk-... API key prefix'leri
API_KEY_PREFIXES = re.compile(r'(sk-|AIza|ya29\.|AIZA)[A-Za-z0-9_-]{20,}')


def _read_py(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ── testler ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("src_file", ALL_PY, ids=lambda f: f.name)
def test_no_real_telegram_token_in_source(src_file: Path):
    """Hiçbir Python dosyasında gerçek Telegram bot token olmamalı."""
    content = _read_py(src_file)
    # Pattern: 8-12 rakam : 35+ karakter
    matches = TELEGRAM_TOKEN_RE.findall(content)
    # Yanlış pozitif eleyici: test/örnek metinlerindeki placeholder'lar hariç
    real = [m for m in matches if "your_bot" not in m and "placeholder" not in m]
    assert not real, (
        f"{src_file.name} içinde gerçek Telegram token görünüyor: {real}\n"
        "BotFather → /revoke ile iptal et, .env.example'a bak."
    )


def test_env_example_exists():
    """.env.example dosyası repo'da olmalı."""
    assert (ROOT / ".env.example").exists(), ".env.example eksik"


def test_env_example_has_no_real_values():
    """.env.example sadece placeholder içermeli, gerçek değer olmamalı."""
    path = ROOT / ".env.example"
    if not path.exists():
        pytest.skip(".env.example yok")
    content = path.read_text()
    # Gerçek Telegram token formatı arama
    assert not TELEGRAM_TOKEN_RE.search(content), (
        ".env.example içinde gerçek Telegram token var!"
    )
    # sk- prefix'li gerçek key
    assert not API_KEY_PREFIXES.search(content), (
        ".env.example içinde gerçek API key var!"
    )


def test_gitignore_covers_env_files():
    """.gitignore .env'yi ve config.json'ı kapsıyor olmalı."""
    gi = (ROOT / ".gitignore").read_text()
    assert ".env" in gi, ".gitignore .env'yi kapsamıyor"
    assert "config.json" in gi, ".gitignore config.json'ı kapsamıyor"


def test_gitignore_covers_secret_patterns():
    """.gitignore *.secret, *.token gibi geniş pattern'leri içermeli."""
    gi = (ROOT / ".gitignore").read_text()
    assert "*.secret" in gi or "secrets.*" in gi, (
        ".gitignore *.secret / secrets.* pattern'i eksik"
    )
    assert "*.token" in gi, ".gitignore *.token pattern'i eksik"


def test_no_real_token_in_env_files():
    """.env dosyası varsa gerçek token içerip içermediğini kontrol et."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        pytest.skip(".env dosyası yok (kurulmamış)")
    content = env_path.read_text()
    # .env varsa ama içindeki value placeholder mı gerçek mi?
    # Sadece "your_" veya "YOUR_" geçiyorsa placeholder sayarız
    for line in content.splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        if not val or "your_" in val.lower() or val.endswith("_here"):
            continue
        # Gerçek token format kontrolü
        if TELEGRAM_TOKEN_RE.fullmatch(val):
            pytest.skip(
                f".env içinde gerçek Telegram token var ({key}) — "
                "bu normal (canlı kullanım), test dışı tutuldu"
            )


def test_config_py_reads_token_from_env_not_hardcode():
    """config.py Telegram tokenı env'den okumalı, hardcode olmamalı."""
    content = (ROOT / "config.py").read_text()
    # TELEGRAM_TOKEN env değişkeninden okunduğunu doğrula
    assert "TELEGRAM_TOKEN" in content, (
        "config.py TELEGRAM_TOKEN env okumayı içermiyor"
    )
    # telegram_token: str = "" fieldı olabilir (default boş), bu OK
    # Ama gerçek token string olarak olmamalı
    assert not TELEGRAM_TOKEN_RE.search(content), (
        "config.py içinde hardcoded Telegram token var!"
    )


def test_no_hardcoded_secrets_in_notify_py():
    """notify.py token veya key içermemeli."""
    content = (ROOT / "notify.py").read_text()
    assert not TELEGRAM_TOKEN_RE.search(content), (
        "notify.py içinde hardcoded Telegram token var!"
    )


def test_env_example_has_required_keys():
    """.env.example gerekli alanları içermeli."""
    path = ROOT / ".env.example"
    if not path.exists():
        pytest.skip(".env.example yok")
    content = path.read_text()
    required = ["TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"]
    for key in required:
        assert key in content, f".env.example'da {key} eksik"
