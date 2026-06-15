"""Komut kayıt defteri — tüm komutlar ve metadata."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Command:
    command_tr: str          # /tara
    command_en: str          # /scan
    aliases: list[str]       # ["/tara", "/scan", "/ara"]
    category: str            # Analiz / Trade / Otonom / Bilgi / Ayar
    description_tr: str
    description_en: str
    example_tr: str          # /tara kripto
    example_en: str          # /scan crypto
    handler_name: str        # "tara"  (op name after alias resolution)
    tags: list[str] = field(default_factory=list)
    requires_position: bool = False
    requires_no_position: bool = False
    requires_scalp_enabled: bool = False
    requires_leverage_enabled: bool = False
    risk_level: str = "low"   # low / medium / high
    visible_in_help: bool = True
    sub_commands: list[str] = field(default_factory=list)  # sub-args for palette expansion


REGISTRY: list[Command] = [
    # ── Analiz ──────────────────────────────────────────────────────────────
    Command(
        command_tr="/tara",
        command_en="/scan",
        aliases=["/tara", "/scan", "/ara"],
        category="Analiz",
        description_tr="Piyasada alım fırsatı ara",
        description_en="Scan market for trading opportunities",
        example_tr="/tara kripto",
        example_en="/scan crypto",
        handler_name="tara",
        tags=["scan", "market", "analysis", "fırsat"],
        risk_level="low",
        visible_in_help=True,
        sub_commands=["kripto", "long", "short", "scalp", "day", "swing",
                      "kaldirac", "global", "forex", "emtia", "endeks",
                      "crypto", "leverage"],
    ),
    Command(
        command_tr="/durum",
        command_en="/status",
        aliases=["/durum", "/status"],
        category="Analiz",
        description_tr="Açık pozisyonları göster",
        description_en="Show open positions",
        example_tr="/durum",
        example_en="/status",
        handler_name="durum",
        tags=["status", "positions", "pozisyon"],
        requires_position=True,
        risk_level="low",
        visible_in_help=True,
    ),
    Command(
        command_tr="/detay",
        command_en="/details",
        aliases=["/detay", "/details"],
        category="Analiz",
        description_tr="Enstrüman detayını göster",
        description_en="Show instrument detail",
        example_tr="/detay BTCUSDT",
        example_en="/details BTCUSDT",
        handler_name="detay",
        tags=["detail", "info", "data quality", "veri kalitesi"],
        risk_level="low",
        visible_in_help=True,
    ),
    Command(
        command_tr="/performans",
        command_en="/performance",
        aliases=["/performans", "/performance"],
        category="Analiz",
        description_tr="Performans istatistikleri",
        description_en="Performance statistics",
        example_tr="/performans",
        example_en="/performance",
        handler_name="performans",
        tags=["performance", "stats", "istatistik"],
        risk_level="low",
        visible_in_help=True,
    ),
    Command(
        command_tr="/gecmis",
        command_en="/history",
        aliases=["/gecmis", "/history"],
        category="Analiz",
        description_tr="Son 10 işlemi göster",
        description_en="Show last 10 trades",
        example_tr="/gecmis",
        example_en="/history",
        handler_name="gecmis",
        tags=["history", "geçmiş", "trades"],
        risk_level="low",
        visible_in_help=True,
    ),
    # ── Trade ────────────────────────────────────────────────────────────────
    Command(
        command_tr="/al",
        command_en="/buy",
        aliases=["/al", "/buy"],
        category="Trade",
        description_tr="Spot long al",
        description_en="Buy spot long",
        example_tr="/al BTCUSDT 500",
        example_en="/buy BTCUSDT 500",
        handler_name="al",
        tags=["buy", "al", "long", "spot"],
        risk_level="medium",
        visible_in_help=True,
    ),
    Command(
        command_tr="/sat",
        command_en="/sell",
        aliases=["/sat", "/sell"],
        category="Trade",
        description_tr="Pozisyon sat/kapat",
        description_en="Sell/close position",
        example_tr="/sat BTCUSDT",
        example_en="/sell BTCUSDT",
        handler_name="sat",
        tags=["sell", "sat", "close", "kapat"],
        requires_position=True,
        risk_level="medium",
        visible_in_help=True,
    ),
    Command(
        command_tr="/short",
        command_en="/short",
        aliases=["/short"],
        category="Trade",
        description_tr="Short paper aç",
        description_en="Open short paper position",
        example_tr="/short BTCUSDT 500",
        example_en="/short BTCUSDT 500",
        handler_name="short",
        tags=["short", "düşüş", "bear"],
        risk_level="high",
        visible_in_help=True,
    ),
    Command(
        command_tr="/koru",
        command_en="/protect",
        aliases=["/koru", "/protect"],
        category="Trade",
        description_tr="Stop/hedef belirle",
        description_en="Set stop/target levels",
        example_tr="/koru BTCUSDT",
        example_en="/protect BTCUSDT",
        handler_name="koru",
        tags=["protect", "stop", "target", "hedef"],
        requires_position=True,
        risk_level="low",
        visible_in_help=True,
    ),
    Command(
        command_tr="/onayla",
        command_en="/approve",
        aliases=["/onayla", "/approve"],
        category="Trade",
        description_tr="Claude önerisini onayla",
        description_en="Approve Claude suggestion",
        example_tr="/onayla 1",
        example_en="/approve 1",
        handler_name="onayla",
        tags=["approve", "onayla", "confirm"],
        risk_level="medium",
        visible_in_help=True,
        sub_commands=["1", "2", "3", "hepsi", "all"],
    ),
    Command(
        command_tr="/reddet",
        command_en="/reject",
        aliases=["/reddet", "/reject"],
        category="Trade",
        description_tr="Öneriyi reddet",
        description_en="Reject suggestion",
        example_tr="/reddet",
        example_en="/reject",
        handler_name="reddet",
        tags=["reject", "reddet", "cancel"],
        risk_level="low",
        visible_in_help=True,
    ),
    Command(
        command_tr="/uygula",
        command_en="/apply",
        aliases=["/uygula", "/apply"],
        category="Trade",
        description_tr="Claude kararını uygula",
        description_en="Apply Claude decision",
        example_tr="/uygula BTCUSDT",
        example_en="/apply BTCUSDT",
        handler_name="uygula",
        tags=["apply", "uygula", "execute"],
        requires_position=True,
        risk_level="medium",
        visible_in_help=True,
        sub_commands=["hepsi", "all"],
    ),
    # ── Otonom ───────────────────────────────────────────────────────────────
    Command(
        command_tr="/otonom",
        command_en="/auto",
        aliases=["/otonom", "/auto"],
        category="Otonom",
        description_tr="Otonom kontrol",
        description_en="Autonomous control",
        example_tr="/otonom ac",
        example_en="/auto on",
        handler_name="otonom",
        tags=["auto", "otonom", "autonomous"],
        risk_level="medium",
        visible_in_help=True,
        sub_commands=["ac", "kapat", "durum", "mod", "ayar", "sifirla",
                      "on", "off", "status", "mode", "set", "reset"],
    ),
    Command(
        command_tr="/scalp",
        command_en="/scalp",
        aliases=["/scalp"],
        category="Otonom",
        description_tr="Scalp modu",
        description_en="Scalp mode",
        example_tr="/scalp ac",
        example_en="/scalp on",
        handler_name="scalp",
        tags=["scalp", "hızlı", "fast"],
        risk_level="high",
        visible_in_help=True,
        sub_commands=["ac", "kapat", "durum", "on", "off", "status"],
    ),
    Command(
        command_tr="/kaldirac",
        command_en="/leverage",
        aliases=["/kaldirac", "/leverage"],
        category="Otonom",
        description_tr="Kaldıraç paper modu",
        description_en="Leverage paper mode",
        example_tr="/kaldirac ac",
        example_en="/leverage on",
        handler_name="kaldirac",
        tags=["leverage", "kaldıraç", "margin"],
        risk_level="high",
        visible_in_help=True,
        sub_commands=["ac", "kapat", "durum", "on", "off", "status"],
    ),
    # ── Ayar ────────────────────────────────────────────────────────────────
    Command(
        command_tr="/ekle",
        command_en="/add",
        aliases=["/ekle", "/add"],
        category="Ayar",
        description_tr="İzleme listesine ekle",
        description_en="Add to watchlist",
        example_tr="/ekle BTCUSDT",
        example_en="/add BTCUSDT",
        handler_name="ekle",
        tags=["add", "ekle", "watchlist"],
        risk_level="low",
        visible_in_help=True,
    ),
    Command(
        command_tr="/cikar",
        command_en="/remove",
        aliases=["/cikar", "/remove"],
        category="Ayar",
        description_tr="İzleme listesinden çıkar",
        description_en="Remove from watchlist",
        example_tr="/cikar BTCUSDT",
        example_en="/remove BTCUSDT",
        handler_name="cikar",
        tags=["remove", "çıkar", "watchlist"],
        risk_level="low",
        visible_in_help=True,
    ),
    Command(
        command_tr="/model",
        command_en="/model",
        aliases=["/model"],
        category="Ayar",
        description_tr="Claude modelini değiştir",
        description_en="Change Claude model",
        example_tr="/model sonnet",
        example_en="/model sonnet",
        handler_name="model",
        tags=["model", "claude", "ai"],
        risk_level="low",
        visible_in_help=True,
        sub_commands=["sonnet", "opus", "haiku", "varsayilan"],
    ),
    Command(
        command_tr="/canli",
        command_en="/live",
        aliases=["/canli", "/live"],
        category="Ayar",
        description_tr="Binance bağlantısı",
        description_en="Binance connection",
        example_tr="/canli bagla KEY SECRET",
        example_en="/live connect KEY SECRET",
        handler_name="canli",
        tags=["live", "canlı", "binance", "connection"],
        risk_level="low",
        visible_in_help=True,
        sub_commands=["bagla", "bakiye", "kes", "mod"],
    ),
    # ── Diğer ────────────────────────────────────────────────────────────────
    Command(
        command_tr="/yardim",
        command_en="/help",
        aliases=["/yardim", "/help", "/h"],
        category="Diğer",
        description_tr="Yardım göster",
        description_en="Show help",
        example_tr="/yardim",
        example_en="/help",
        handler_name="yardim",
        tags=["help", "yardım"],
        risk_level="low",
        visible_in_help=True,
    ),
    Command(
        command_tr="/bakiye",
        command_en="/balance",
        aliases=["/bakiye", "/balance", "/wallet"],
        category="Diğer",
        description_tr="Paper bakiyeyi göster / ayarla",
        description_en="Show / set paper balance",
        example_tr="/bakiye ayarla 100",
        example_en="/balance set 100",
        handler_name="bakiye",
        tags=["bakiye", "balance", "cash", "nakit"],
        risk_level="low",
        visible_in_help=True,
        sub_commands=["ayarla", "set"],
    ),
    Command(
        command_tr="/cikis",
        command_en="/exit",
        aliases=["/cikis", "/exit", "/quit"],
        category="Diğer",
        description_tr="Menüye dön",
        description_en="Return to menu",
        example_tr="/cikis",
        example_en="/exit",
        handler_name="cikis",
        tags=["exit", "çıkış", "quit", "menu", "menü"],
        risk_level="low",
        visible_in_help=True,
    ),
]


def get_context_suggestions(context: dict) -> list[tuple[str, str, str, str]]:
    """Context-aware suggestions when user just typed '/'.
    Returns (cmd_display, category, description_tr, description_en) tuples.
    cmd_display is language-aware (TR command in TR mode, EN in EN mode).
    """
    import i18n
    en = i18n.lang() == "en"
    suggestions = []
    has_pos = context.get("has_positions", False)
    auto_on = context.get("auto_enabled", False)
    scalp_on = context.get("scalp_enabled", False)
    lev_on = context.get("leverage_enabled", False)

    if not has_pos:
        suggestions += [
            ("/scan crypto" if en else "/tara kripto",
             "Analiz", "Kripto piyasasını tara", "Scan crypto market"),
            ("/scan long" if en else "/tara long",
             "Analiz", "Long fırsatlarını tara", "Scan for long opportunities"),
        ]
        if scalp_on:
            suggestions.append((
                "/scan scalp" if en else "/tara scalp",
                "Analiz", "Scalp fırsatlarını tara", "Scan for scalp opportunities",
            ))
        if lev_on:
            suggestions.append((
                "/scan leverage" if en else "/tara kaldirac",
                "Analiz", "Kaldıraçlı fırsatları tara", "Scan for leverage opportunities",
            ))
        if not scalp_on:
            suggestions.append((
                "/scalp on" if en else "/scalp ac",
                "Ayar", "Scalp modunu etkinleştir", "Enable scalp paper mode",
            ))
        if not lev_on:
            suggestions.append((
                "/leverage on" if en else "/kaldirac ac",
                "Ayar", "Kaldıraç paper modunu etkinleştir", "Enable leverage paper mode",
            ))
        if auto_on:
            suggestions += [
                ("/auto status" if en else "/otonom durum",
                 "Otonom", "Otonom durumunu göster", "Show autonomous status"),
                ("/auto off" if en else "/otonom kapat",
                 "Otonom", "Otonom modu durdur", "Stop autonomous mode"),
            ]
        else:
            suggestions += [
                ("/auto on" if en else "/otonom ac",
                 "Otonom", "Otonom modu başlat", "Start autonomous mode"),
                ("/auto mode" if en else "/otonom mod",
                 "Otonom", "Otonom modunu değiştir", "Change autonomous mode"),
            ]
    else:
        suggestions += [
            ("/status" if en else "/durum",
             "Analiz", "Açık pozisyonları göster", "Show open positions"),
            ("/apply all" if en else "/uygula hepsi",
             "Trade", "Tüm Claude kararlarını uygula", "Apply all Claude decisions"),
        ]
        if auto_on:
            suggestions += [
                ("/auto status" if en else "/otonom durum",
                 "Otonom", "Otonom durumunu göster", "Show autonomous status"),
                ("/auto off" if en else "/otonom kapat",
                 "Otonom", "Otonom modu durdur", "Stop autonomous mode"),
            ]
        else:
            suggestions.append((
                "/auto on" if en else "/otonom ac",
                "Otonom", "Otonom modu başlat", "Start autonomous mode",
            ))
        suggestions.append((
            "/scan crypto" if en else "/tara kripto",
            "Analiz", "Kripto piyasasını tara", "Scan crypto market",
        ))

    # Her zaman göster
    suggestions += [
        ("/balance" if en else "/bakiye",
         "Diğer", "Paper bakiyeyi göster / ayarla", "Show / set paper balance"),
        ("/exit" if en else "/cikis",
         "Diğer", "Menüye dön", "Return to menu"),
    ]

    return suggestions[:8]


def get_palette_suggestions(
    prefix: str,
    context: dict | None = None,
) -> list[tuple[str, str, str, str]]:
    """
    Returns list of (command_display, category, description_tr, description_en) tuples.
    prefix: what user has typed (e.g. "/ta", "/otonom", "/scan")
    context: dict with keys: has_positions, auto_enabled, scalp_enabled, leverage_enabled
    """
    import i18n as _i18n
    if context is None:
        context = {}

    # Just "/" → context-aware suggestions
    if prefix in ("/", ""):
        return get_context_suggestions(context)

    prefix_lower = prefix.lower()
    en_mode = _i18n.lang() == "en"
    results: list[tuple[str, str, str, str]] = []

    for cmd in REGISTRY:
        # Check if any alias starts with prefix
        matched_alias = None
        for alias in cmd.aliases:
            if alias.lower().startswith(prefix_lower):
                matched_alias = alias
                break

        if matched_alias is not None:
            # Prefer active-language command; fallback: show what user is typing
            is_en_input = (
                matched_alias.lower() == cmd.command_en.lower()
                and cmd.command_en != cmd.command_tr
            )
            display_cmd = cmd.command_en if (is_en_input or en_mode) else cmd.command_tr

            # Check if we're at/past an exact command match → expand sub_commands
            if cmd.sub_commands:
                exact_cmd_tr = cmd.command_tr.lower()
                exact_cmd_en = cmd.command_en.lower()
                is_exact_match = prefix_lower in (
                    exact_cmd_tr, exact_cmd_en,
                    exact_cmd_tr + " ", exact_cmd_en + " ",
                )
                has_space = (
                    prefix_lower.startswith(exact_cmd_tr + " ")
                    or prefix_lower.startswith(exact_cmd_en + " ")
                )

                if is_exact_match or has_space:
                    sub_prefix = ""
                    if has_space:
                        if prefix_lower.startswith(exact_cmd_tr + " "):
                            sub_prefix = prefix_lower[len(exact_cmd_tr) + 1:]
                        elif prefix_lower.startswith(exact_cmd_en + " "):
                            sub_prefix = prefix_lower[len(exact_cmd_en) + 1:]

                    for sub in cmd.sub_commands:
                        if sub_prefix and not sub.lower().startswith(sub_prefix):
                            continue
                        display = f"{display_cmd} {sub}"
                        results.append((display, cmd.category, cmd.description_tr, cmd.description_en))
                    continue

            # Just show the command itself
            results.append((
                display_cmd,
                cmd.category,
                cmd.description_tr,
                cmd.description_en,
            ))
            continue

        # Also check sub-command expansion when prefix includes a space
        # e.g. "/scan crypt" → expand /tara sub-commands
        if " " in prefix_lower:
            parts = prefix_lower.split(" ", 1)
            base_part = parts[0]
            sub_part = parts[1]

            base_matches = any(
                alias.lower() == base_part
                for alias in cmd.aliases
            )
            if base_matches and cmd.sub_commands:
                base_cmd = cmd.command_en if en_mode else cmd.command_tr
                for sub in cmd.sub_commands:
                    if sub_part and not sub.lower().startswith(sub_part):
                        continue
                    display = f"{base_cmd} {sub}"
                    results.append((display, cmd.category, cmd.description_tr, cmd.description_en))

    return results[:8]


def fuzzy_match_commands(user_input: str, n: int = 3) -> list[str]:
    """
    Returns list of close command matches for typo correction.
    Uses difflib.get_close_matches.
    """
    import difflib
    # Build candidate list from all commands
    candidates = []
    for cmd in REGISTRY:
        candidates.append(cmd.command_tr)
        candidates.append(cmd.command_en)
        for sub in cmd.sub_commands[:5]:
            candidates.append(f"{cmd.command_tr} {sub}")
            candidates.append(f"{cmd.command_en} {sub}")
    return difflib.get_close_matches(user_input, candidates, n=n, cutoff=0.55)


def help_text(lang: str = "tr") -> str:
    """Generate help text from registry. lang: 'tr' or 'en'."""
    from collections import defaultdict
    cats: dict[str, list[Command]] = defaultdict(list)
    for cmd in REGISTRY:
        if cmd.visible_in_help:
            cats[cmd.category].append(cmd)

    lines = []
    if lang == "tr":
        lines.append("[bold cyan]trade-k komutları:[/]")
    else:
        lines.append("[bold cyan]trade-k commands:[/]")

    for cat, cmds in cats.items():
        lines.append(f"\n[bold gold3]{cat}[/]")
        for cmd in cmds:
            if lang == "tr":
                alias_str = f"  [grey50]({cmd.command_en})[/]" if cmd.command_en != cmd.command_tr else ""
                lines.append(
                    f"  [bold]{cmd.command_tr}[/]{alias_str}  "
                    f"[grey70]{cmd.description_tr}[/]"
                )
                if cmd.example_tr:
                    lines.append(f"    [grey50]örn: {cmd.example_tr}[/]")
            else:
                alias_str = f"  [grey50]({cmd.command_tr})[/]" if cmd.command_en != cmd.command_tr else ""
                lines.append(
                    f"  [bold]{cmd.command_en}[/]{alias_str}  "
                    f"[grey70]{cmd.description_en}[/]"
                )
                if cmd.example_en:
                    lines.append(f"    [grey50]ex: {cmd.example_en}[/]")

    if lang == "tr":
        lines.append("\n[grey50]Komut aramak için / yazın — öneri paneli açılır[/]")
    else:
        lines.append("\n[grey50]Type / to open the command suggestion panel[/]")

    return "\n".join(lines)
