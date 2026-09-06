# ═══════════════════════════════════════════════════════════════
# 🔧 عدّة التصميم الموحدة — Cookies Tracker Components V2
# نقل اللغة البصرية الكاملة من بوت السحب ZEUS:
#   حاوية واحدة (Container) بلون accent حسب الحالة + رأس Section
#   بصورة مصغرة (للبوت أو للعضو المعنيّ) + فواصل (Separator) +
#   شريط تقدم ▰▱ + قائمة مراحل ✓ ▸ · ✗ ⊘ + تذييل -# Cookies Tracker
#   + أزرار بنفس الأنماط.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from typing import Awaitable, Callable, Iterable, Optional, Union

import discord
from discord import ui

# ── الألوان الأربعة (نفس ألوان بوت السحب بالضبط) ──
ACCENT_GOLD = 0xd4af37    # الذهبي — الانتظار / المعلومات / البطاقات العامة
ACCENT_GREEN = 0x57f287   # الأخضر — النجاح / الاكتمال / الحفظ
ACCENT_RED = 0xed4245     # الأحمر — الفشل / الرفض
ACCENT_GRAY = 0x95a5a6    # الرمادي — الإلغاء / المحذوف

BOT_SIGNATURE = "Cookies Tracker"


# ───────────────────────────────────────────────────────────────
# عناصر البناء الخام (نفس أنواع بوت السحب: 10 نص، 14 فاصل، 9 قسم)
# ───────────────────────────────────────────────────────────────
def text(content: str) -> ui.TextDisplay:
    """TextDisplay — type 10."""
    return ui.TextDisplay(content)


def sep(spacing: int = 1) -> ui.Separator:
    """فاصل — type 14 (small=1 / large=2) تمامًا كالفاصل في بوت السحب."""
    return ui.Separator(
        visible=True,
        spacing=discord.SeparatorSpacing.large if spacing == 2 else discord.SeparatorSpacing.small,
    )


def header(lines: Iterable[str], avatar_url: Optional[str] = None):
    """رأس البطاقة: Section (type 9) بصورة البوت المصغرة (type 11)،
    أو نص عادي إن لم تتوفر صورة — نفس سلوك headerBlock في بوت السحب."""
    content = "\n\n".join(lines)
    if avatar_url:
        return ui.Section(text(content), accessory=ui.Thumbnail(avatar_url))
    return text(content)


def member_header(lines: Iterable[str], member) -> Section | TextDisplay:
    """رأس البطاقة بصورة العضو المعنيّ — تُستخدم في كل بطاقات الأعضاء
    (/شغل، /الأعضاء، الإيصالات، المكافآت…) بدل صورة البوت."""
    url: Optional[str] = None
    try:
        if member is not None and hasattr(member, "display_avatar"):
            url = member.display_avatar.url
    except Exception:
        url = None
    return header(lines, url)


def clamp(value: Optional[str], limit: int) -> str:
    value = value or ""
    return value if len(value) <= limit else value[: limit - 1] + "…"


# ───────────────────────────────────────────────────────────────
# شريط التقدم (▰▱ × 10) — منسوخ حرفيًا من progressBar في بوت السحب
# ───────────────────────────────────────────────────────────────
def progress_bar(done: float, total: float, cells: int = 10) -> str:
    if total <= 0:
        return "▱" * cells
    ratio = min(1.0, max(0.0, done / total))
    filled = round(ratio * cells)
    if done > 0 and filled == 0:
        filled = 1
    return "▰" * filled + "▱" * (cells - filled)


def progress_line(done: float, total: float) -> str:
    """سطر التقدم القياسي: ▰▰▰▱▱▱▱▱▱▱ **3 / 5**"""
    return f"{progress_bar(done, total)} **{int(done)} / {int(total)}**"


# ───────────────────────────────────────────────────────────────
# الحاوية الأساسية — Card (LayoutView بحاوية واحدة type 17)
# ───────────────────────────────────────────────────────────────
def container(accent: int, *children) -> ui.Container:
    """حاوية Container (type 17) — تُستخدم داخل العروض الديناميكية
    التي تُعيد بناء محتواها (LayoutView يضيف الحاوية مباشرة)."""
    return ui.Container(*children, accent_color=accent)


class Card(ui.LayoutView):
    """بطاقة Components V2: حاوية واحدة بلون accent كما في بوت السحب.
    مثال: Card(ACCENT_GOLD, header(["## 📖 Cookies Tracker"], url), sep(2), text("نص"))"""

    def __init__(self, accent: int, *children, timeout: Optional[float] = 300.0):
        super().__init__(timeout=timeout)
        self.add_item(container(accent, *children))

    @property
    def container(self) -> ui.Container:
        return self.children[0]  # type: ignore[return-value]


# ───────────────────────────────────────────────────────────────
# مصانع الأزرار — نفس أنماط بوت السحب:
#   Link=5 / Danger=4 / Secondary=2 / Success=3
# ───────────────────────────────────────────────────────────────
def make_button(
    label: str,
    *,
    style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    callback: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    url: Optional[str] = None,
    emoji: Optional[str] = None,
    disabled: bool = False,
    custom_id: Optional[str] = None,
) -> ui.Button:
    button = ui.Button(label=label, style=style, url=url, emoji=emoji, disabled=disabled, custom_id=custom_id)
    if callback is not None:
        button.callback = callback
    return button


def success_btn(label: str, callback, *, emoji: Optional[str] = None, disabled: bool = False) -> ui.Button:
    return make_button(label, style=discord.ButtonStyle.success, callback=callback, emoji=emoji, disabled=disabled)


def danger_btn(label: str, callback, *, emoji: Optional[str] = None, disabled: bool = False) -> ui.Button:
    return make_button(label, style=discord.ButtonStyle.danger, callback=callback, emoji=emoji, disabled=disabled)


def secondary_btn(label: str, callback, *, emoji: Optional[str] = None, disabled: bool = False) -> ui.Button:
    return make_button(label, style=discord.ButtonStyle.secondary, callback=callback, emoji=emoji, disabled=disabled)


def link_btn(label: str, url: str, *, emoji: Optional[str] = None) -> ui.Button:
    return make_button(label, style=discord.ButtonStyle.link, url=url, emoji=emoji)


def row(*items) -> ui.ActionRow:
    return ui.ActionRow(*items)


def make_select(
    placeholder: str,
    options: list[discord.SelectOption],
    callback,
    *,
    disabled: bool = False,
    max_values: int = 1,
) -> ui.ActionRow:
    """قائمة منسدلة داخل صف ActionRow (كما في بوت السحب — الحد 25 خيارًا)."""
    select = ui.Select(
        placeholder=clamp(placeholder, 150) if placeholder else "اختر…",
        options=options[:25],
        min_values=1,
        max_values=max_values,
        disabled=disabled,
    )
    select.callback = callback
    return ui.ActionRow(select)


def pager_row(
    page: int,
    total_pages: int,
    prev_callback,
    next_callback,
) -> ui.ActionRow:
    """صف التنقل القياسي من بوت السحب: السابق ◀ / صفحة X من Y (معطّل) / التالي ▶"""
    prev = make_button("السابق", style=discord.ButtonStyle.secondary, emoji="◀",
                       callback=prev_callback, disabled=page <= 0)
    indicator = make_button(f"صفحة {page + 1} من {total_pages}",
                            style=discord.ButtonStyle.secondary, disabled=True)
    nxt = make_button("التالي", style=discord.ButtonStyle.secondary, emoji="▶",
                      callback=next_callback, disabled=page >= total_pages - 1)
    return ui.ActionRow(prev, indicator, nxt)


# ───────────────────────────────────────────────────────────────
# بطاقات جاهزة بنفس بنية بوت السحب
# ───────────────────────────────────────────────────────────────
def simple_card(
    accent: int,
    title: str,
    lines: Iterable[str],
    *,
    avatar_url: Optional[str] = None,
    signature: bool = True,
    timeout: Optional[float] = 300.0,
) -> Card:
    """بطاقة قياسية: رأس بصورة + فاصل كبير + المحتوى + تذييل -# Cookies Tracker."""
    children: list = [header([f"## {title}"], avatar_url), sep(2)]
    body = "\n\n".join(l for l in lines if l)
    children.append(text(clamp(body, 3800)))
    if signature:
        children += [sep(), text(f"-# {BOT_SIGNATURE}")]
    return Card(accent, *children, timeout=timeout)


def success_card(title: str, lines: Iterable[str], *, avatar_url: Optional[str] = None, signature: bool = True) -> Card:
    return simple_card(ACCENT_GREEN, title, lines, avatar_url=avatar_url, signature=signature)


def error_card(title: str, lines: Iterable[str], *, avatar_url: Optional[str] = None, signature: bool = True) -> Card:
    return simple_card(ACCENT_RED, title, lines, avatar_url=avatar_url, signature=signature)


def info_card(title: str, lines: Iterable[str], *, avatar_url: Optional[str] = None, signature: bool = True) -> Card:
    return simple_card(ACCENT_GOLD, title, lines, avatar_url=avatar_url, signature=signature)


def muted_card(title: str, lines: Iterable[str], *, avatar_url: Optional[str] = None, signature: bool = True) -> Card:
    return simple_card(ACCENT_GRAY, title, lines, avatar_url=avatar_url, signature=signature)


# بطاقات الرفض القياسية — نفس نصوص بوت السحب حرفيًا
PERMISSION_TITLE = "🔒 لا تملك صلاحية"
PERMISSION_DETAIL = "هذا الأمر متاح لأدوار محددة فقط."


def permission_card(avatar_url: Optional[str] = None) -> Card:
    return error_card(PERMISSION_TITLE, [PERMISSION_DETAIL], avatar_url=avatar_url)


def channel_card(allowed_channels: list, avatar_url: Optional[str] = None) -> Card:
    channels_str = ", ".join(
        f"<#{ch}>" if isinstance(ch, int) else f"#{ch}" for ch in allowed_channels
    ) or "لا توجد قنوات محددة"
    return error_card(
        "🔒 القناة غير مسموحة",
        [f"استخدم هذا الأمر فقط في أحد الرومات: {channels_str}."],
        avatar_url=avatar_url,
    )
