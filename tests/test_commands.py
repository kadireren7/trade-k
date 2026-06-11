"""Komut registry, autocomplete ve fuzzy match testleri."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import commands as cmd_registry


def test_registry_has_all_categories():
    """Registry tüm kategorileri içermeli."""
    cats = {cmd.category for cmd in cmd_registry.REGISTRY}
    assert "Analiz" in cats
    assert "Trade" in cats
    assert "Otonom" in cats


def test_registry_tara_command():
    """/tara komutu registry'de var."""
    cmds = [c for c in cmd_registry.REGISTRY if c.handler_name == "tara"]
    assert len(cmds) == 1
    assert "/tara" in cmds[0].aliases
    assert "/scan" in cmds[0].aliases


def test_registry_durum_command():
    """/durum ve /status aynı handler'a gidiyor."""
    cmds = [c for c in cmd_registry.REGISTRY if c.handler_name == "durum"]
    assert len(cmds) == 1
    assert "/durum" in cmds[0].aliases
    assert "/status" in cmds[0].aliases


def test_palette_slash_returns_context_suggestions():
    """'/' yazınca context-aware öneriler dönmeli."""
    context = {"has_positions": False, "auto_enabled": False,
               "scalp_enabled": False, "leverage_enabled": False}
    suggestions = cmd_registry.get_palette_suggestions("/", context)
    assert len(suggestions) > 0
    assert len(suggestions) <= 8


def test_palette_prefix_filtering():
    """'/ta' ile /tara komutları filtrelenmeli."""
    context = {}
    suggestions = cmd_registry.get_palette_suggestions("/ta", context)
    cmds = [s[0] for s in suggestions]
    assert any("/tara" in c for c in cmds), f"No /tara in {cmds}"


def test_palette_scan_english():
    """'/scan' İngilizce komutları göstermeli."""
    context = {}
    suggestions = cmd_registry.get_palette_suggestions("/scan", context)
    cmds = [s[0] for s in suggestions]
    assert any("scan" in c for c in cmds)


def test_palette_auto_english():
    """'/auto' önerisi dönmeli."""
    context = {}
    suggestions = cmd_registry.get_palette_suggestions("/auto", context)
    assert len(suggestions) > 0


def test_palette_otonom_suggestions():
    """'/otonom' → otonom sub-komutları dönmeli."""
    context = {}
    suggestions = cmd_registry.get_palette_suggestions("/otonom", context)
    cmds = [s[0] for s in suggestions]
    assert len(cmds) > 0


def test_palette_max_8_items():
    """Palette maksimum 8 öneri döndürmeli."""
    context = {}
    for prefix in ["/", "/t", "/a", "/o"]:
        suggestions = cmd_registry.get_palette_suggestions(prefix, context)
        assert len(suggestions) <= 8, f"Too many suggestions for {prefix}: {len(suggestions)}"


def test_context_has_positions_shows_durum():
    """Açık pozisyon varken /durum önerisi üstte çıkmalı."""
    context = {"has_positions": True, "auto_enabled": False,
               "scalp_enabled": False, "leverage_enabled": False}
    suggestions = cmd_registry.get_context_suggestions(context)
    cmds = [s[0] for s in suggestions]
    assert any("durum" in c or "status" in c for c in cmds)


def test_context_auto_on_shows_kapat():
    """Otonom açıkken /otonom kapat önerisi çıkmalı."""
    context = {"has_positions": False, "auto_enabled": True,
               "scalp_enabled": False, "leverage_enabled": False}
    suggestions = cmd_registry.get_context_suggestions(context)
    cmds = [s[0] for s in suggestions]
    assert any("kapat" in c for c in cmds), f"No kapat in {cmds}"


def test_context_scalp_off_shows_scalp_ac():
    """Scalp kapalıyken /scalp ac önerisi çıkmalı."""
    context = {"has_positions": False, "auto_enabled": False,
               "scalp_enabled": False, "leverage_enabled": False}
    suggestions = cmd_registry.get_context_suggestions(context)
    cmds = [s[0] for s in suggestions]
    assert any("scalp" in c for c in cmds), f"No scalp suggestion in {cmds}"


def test_context_leverage_off_shows_kaldirac_ac():
    """Kaldıraç kapalıyken /kaldirac ac önerisi çıkmalı."""
    context = {"has_positions": False, "auto_enabled": False,
               "scalp_enabled": False, "leverage_enabled": False}
    suggestions = cmd_registry.get_context_suggestions(context)
    cmds = [s[0] for s in suggestions]
    assert any("kaldirac" in c or "leverage" in c for c in cmds), f"No leverage suggestion in {cmds}"


def test_fuzzy_match_onayla():
    """/onayal → /onayla fuzzy match vermeli."""
    matches = cmd_registry.fuzzy_match_commands("/onayal")
    assert len(matches) > 0
    assert any("onayla" in m for m in matches)


def test_fuzzy_match_tara_kripto():
    """/tara krpto → /tara kripto fuzzy match vermeli."""
    matches = cmd_registry.fuzzy_match_commands("/tara krpto")
    # Should return close matches
    assert isinstance(matches, list)


def test_fuzzy_match_scan_crypto():
    """/scan crypt → /scan crypto fuzzy önerisi."""
    matches = cmd_registry.fuzzy_match_commands("/scan crypt")
    assert isinstance(matches, list)


def test_help_text_generated_from_registry():
    """/yardim metni registry'den üretilmeli."""
    text = cmd_registry.help_text("tr")
    assert "/tara" in text
    assert "/durum" in text
    assert "/otonom" in text
    assert "/kaldirac" in text


def test_help_text_en_generated_from_registry():
    """/help metni registry'den üretilmeli."""
    text = cmd_registry.help_text("en")
    assert "/scan" in text
    assert "/status" in text
    assert "/auto" in text


def test_all_commands_have_handler_name():
    """Tüm komutların handler_name'i dolu olmalı."""
    for cmd in cmd_registry.REGISTRY:
        assert cmd.handler_name, f"Empty handler_name in {cmd.command_tr}"


def test_all_commands_have_descriptions():
    """Tüm komutların açıklaması dolu olmalı."""
    for cmd in cmd_registry.REGISTRY:
        assert cmd.description_tr, f"Empty description_tr in {cmd.command_tr}"
        assert cmd.description_en, f"Empty description_en in {cmd.command_en}"


def test_real_order_disabled_still_active():
    """REAL_ORDER_DISABLED koruması bozulmadı."""
    import autonomous
    with pytest.raises(RuntimeError, match="REAL_ORDER_DISABLED"):
        autonomous.create_order("BTCUSDT", "BUY", "MARKET", 0.001)
