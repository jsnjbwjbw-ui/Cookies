# ═══════════════════════════════════════════════════════════════
# 🍪 /أزورا — لوحة التحكم الكاملة لنظام ربط أعمال الفريق:
#
#   • حالة النظام: الفريق، الأعمال المعروفة، المرتبطة، آخر مزامنة،
#     قناة الإعلانات، المفاتيح، مدة المزامنة — كل معلومة بسطر.
#   • مزامنة الآن — تنفّذ دورة كاملة فورًا ويعرض التقرير.
#   • ربط عمل ← اختيار عمل البوت ثم عمل أزورا (سيلكت + اقتراح ذكي
#     بالأسماء) ← تأكيد ← جلب فصول فوري — بلا كتابة إطلاقًا.
#   • ربط تلقائي بالأسماء — يربط كل ما تطابق أسماؤه بنفسه.
#   • فك ربط، تسمية عربية (مع ترحيل سجلات العمل إلى الاسم الجديد)،
#     قناة الإعلانات (سيلكت قنوات)، مفاتيح النظام، مدة المزامنة،
#     تغيير رابط الفريق (يقبل الرابط الكامل أو السلاغ مع تحقق حي).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

import discord
from discord import app_commands, ui
from state import bot
from helpers.safe_view import SafeLayoutView
from helpers.core import (
    SETTINGS, is_admin, channel_allowed, load_works, save_works,
    load_records, log_audit,
)
from azora import client, store
from azora.sync import run_sync_cycle
from ui import cards


def _bot_avatar() -> str | None:
    return bot.user.display_avatar.url if bot.user else None


def _fmt_ago(iso: str | None) -> str:
    dt = None
    if iso:
        try:
            dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        except Exception:
            dt = None
    if not dt:
        return "—"
    delta = (datetime.now(timezone.utc) - dt).total_seconds()
    if delta < 60:
        return "قبل أقل من دقيقة"
    if delta < 3600:
        return f"قبل {int(delta // 60)} دقيقة"
    if delta < 86400:
        return f"قبل {int(delta // 3600)} ساعة"
    return f"قبل {int(delta // 86400)} يوم"


def normalize_name(s: str) -> str:
    """تطبيع الأسماء للمطابقة الذكية (حروف/أرقام فقط بلا مسافات أو رموز)."""
    return re.sub(r"[^\w\u0600-\u06FF]+", "", (s or "").lower())


def _page_of(items: list, page: int, per: int) -> tuple[list, int]:
    total = max(1, (len(items) + per - 1) // per)
    page = min(max(0, page), total - 1)
    return items[page * per: (page + 1) * per], total


def slug_from_input(text: str) -> str:
    """`https://azorafly.com/teams/cookies` أو `cookies` → `cookies`."""
    text = (text or "").strip()
    m = re.search(r"azorafly\.com/teams/([A-Za-z0-9_\-]+)", text)
    if m:
        return m.group(1)
    m = re.fullmatch(r"([A-Za-z0-9_\-]+)", text)
    return m.group(1) if m else ""


async def _fetch_and_cache_chapters(slug: str, team_name: str = "") -> int | None:
    """جلب فصول عمل أزورا وتخزينها — يعيد العدد أو None عند الفشل."""
    try:
        chapters = await client.fetch_work_chapters(slug)
    except client.AzoraError as e:
        print(f"[AZORA] fetch_work_chapters({slug}) فشل: {e}")
        return None
    await store.save_chapters_entry(slug, {
        "numbers": [c["number"] for c in chapters],
        "count": len(chapters),
        "updated_at": "",
        "team_name": team_name,
    })
    return len(chapters)


async def _link_work(work: dict, slug: str, entry: dict, by_name: str) -> str:
    """تنفيذ الربط فعليًا — يعيد سطر النتيجة."""
    work["azora"] = {
        "slug": slug,
        "post_id": entry.get("post_id"),
        "title_en": entry.get("title_en") or "",
        "cover": entry.get("cover") or "",
        "team_name": entry.get("team_name") or "",
        "linked_at": datetime.now(timezone.utc).isoformat(),
        "linked_by": by_name,
    }
    count = await _fetch_and_cache_chapters(slug, entry.get("team_name") or "")
    await log_audit("ربط_أزورا", 0, None,
                    f"ربط «{work.get('name')}» بـ {slug} "
                    f"(فصول: {count if count is not None else 'لم تُجلب بعد'})")
    if count is None:
        return ("ارتبط لكن لم أستطع جلب فصوله الآن — سيكمل نظام المزامنة الجلب تلقائيًا "
                "ويُفتح التسجيل المقيّد حينها.")
    return f"فصوله المنشورة: {count} — التسجيل مفتوح للفصول الموجودة فقط."


class AzoraHubView(SafeLayoutView):
    """لوحة /أزورا — عرض واحد متعدد الشاشات يُعاد بناؤه حسب self.mode."""

    PER_PAGE = 8

    def __init__(self, guild: discord.Guild, user, back=None):
        super().__init__(timeout=900.0)
        self.guild = guild
        self.user = user
        self.back = back  # مصنع عودة للوحة التحكم (اختياري)
        self.mode = "hub"
        self.page = 0
        self.notice: str | None = None
        self.pending_link_work: dict | None = None
        self.pending_link_slug: str | None = None
        self.pending_unlink: dict | None = None
        self.pending_rename: dict | None = None

    # ── البناء والتنقل ──
    @classmethod
    async def create(cls, guild: discord.Guild, user, back=None):
        self = cls(guild, user, back)
        await self.rebuild_async()
        return self

    async def rebuild_async(self, notice: str | None = None):
        if notice is not None:
            self.notice = notice
        self.clear_items()
        children = await self.route_children()
        self.add_item(cards.container(cards.ACCENT_GOLD, *children))

    async def _show(self, interaction: discord.Interaction, notice: str | None = None):
        self.notice = notice
        await self.rebuild_async(notice)
        await interaction.response.edit_message(view=self)

    async def _show_after_defer(self, interaction: discord.Interaction, notice: str):
        self.notice = notice
        await self.rebuild_async(notice)
        await interaction.message.edit(view=self)

    async def _back_to_dashboard(self, interaction: discord.Interaction):
        parent = await self.back()
        await interaction.response.edit_message(view=parent)

    async def _back_to_hub(self, interaction: discord.Interaction):
        self.mode = "hub"
        self.page = 0
        await self._show(interaction)

    async def _prev_page(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        await self._show(interaction)

    async def _next_page(self, interaction: discord.Interaction):
        self.page += 1
        await self._show(interaction)

    def _back_row(self) -> list:
        if self.back:
            return [cards.sep(),
                    cards.row(cards.secondary_btn("عودة إلى لوحة التحكم",
                                                  self._back_to_dashboard, emoji="↩")),
                    cards.sep()]
        return []

    def _wait_check(self, user_id: int, channel_id: int):
        def check(m: discord.Message):
            return (m.author.id == user_id and m.channel.id == channel_id
                    and not m.content.startswith("!"))
        return check

    async def _wait_timed_out(self, interaction: discord.Interaction, what: str):
        try:
            await interaction.message.edit(view=cards.muted_card(
                "انتهت المهلة",
                [f"لم تصل القيمة خلال دقيقتين — لم يتغير شيء.\nأعد {what} متى شئت."],
                avatar_url=_bot_avatar()))
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════
    # موجّه الشاشات
    # ══════════════════════════════════════════════════════════
    async def route_children(self) -> list:
        mode = self.mode
        if mode == "linked_list":
            return await self._linked_children()
        if mode == "link_pick_work":
            return await self._link_pick_work_children()
        if mode == "link_pick_azora":
            return await self._link_pick_azora_children()
        if mode == "link_confirm":
            return await self._link_confirm_children()
        if mode == "unlink_pick":
            return await self._unlink_pick_children()
        if mode == "unlink_confirm":
            return await self._unlink_confirm_children()
        if mode == "rename_pick":
            return await self._rename_pick_children()
        if mode == "rename_wait":
            return await self._rename_wait_children()
        if mode == "channel_pick":
            return await self._channel_children()
        if mode == "interval_wait":
            return await self._interval_wait_children()
        if mode == "slug_wait":
            return await self._slug_wait_children()
        return await self._hub_children()

    # ══════════════════════════════════════════════════════════
    # شاشة المركز
    # ══════════════════════════════════════════════════════════
    async def _hub_children(self) -> list:
        avatar = _bot_avatar()
        state = await store.load_state()
        cache = await store.load_cache()
        works = await load_works()
        linked = [w for w in works if w.get("azora")]

        team_slug = state.get("team_slug") or client.DEFAULT_TEAM_SLUG
        team_url = f"{client.AZORA_BASE}/teams/{team_slug}"

        if state.get("last_sync_ok") is True:
            sync_state = "نجحت"
        elif state.get("last_sync_ok") is False:
            sync_state = "فشلت"
        else:
            sync_state = "لم تبدأ بعد"

        status_lines = [
            f"**حالة النظام:** {'مفعّل' if state.get('enabled') else 'متوقف'}",
            f"**الفريق:** {state.get('team_name') or 'COOKIES'} — {team_url}",
            f"**أعمال الفريق المعروفة:** {len(cache['works'])}",
            f"**الأعمال المرتبطة بالبوت:** {len(linked)} من {len(works)}",
            f"**آخر مزامنة:** {sync_state} — {_fmt_ago(state.get('last_sync_at'))}",
        ]
        if state.get("last_error"):
            status_lines.append(f"**آخر ملاحظة:** {cards.clamp(str(state['last_error']), 200)}")
        if not state.get("baseline_done"):
            status_lines.append(
                "**الخطوة التالية:** أول مزامنة تسجّل أعمال الفريق الحالية كخط أساس "
                "**بدون** إضافتها للبوت — بعدها فقط يبدأ الاكتشاف التلقائي للجديد والإعلانات.")
        status_lines += [
            "**قناة الإعلانات:** " + (
                f"<#{state.get('announce_channel_id')}>" if state.get("announce_channel_id")
                else "لم تُحدد بعد"),
            f"**الإضافة التلقائية لأعمال جديدة:** {'مفعلة' if state.get('auto_add_new_works', True) else 'معطلة'}",
            f"**إعلانات نزول الفصول:** {'مفعلة' if state.get('announcements_enabled', True) else 'معطلة'}",
            f"**مدة المزامنة:** كل {state.get('sync_interval_minutes') or 10} دقيقة",
            f"**إجمالي المعلَن:** {state.get('announced_count') or 0} فصلًا • **أُضيف تلقائيًا:** {state.get('auto_added_count') or 0} عمل",
        ]

        children: list = [
            cards.header(["## لوحة أزورا",
                          f"<@{self.user.id}> — أعمال الفريق الحقيقية والتسجيل المقيّد بالفصول المنشورة."],
                         avatar),
            cards.sep(2),
            cards.text("### نبضة النظام\n" + "\n".join(status_lines)),
        ]
        if self.notice:
            children += [cards.sep(), cards.text(cards.clamp(self.notice, 1500))]

        en = state.get("enabled", True)
        auto = state.get("auto_add_new_works", True)
        ann = state.get("announcements_enabled", True)
        children += [
            cards.sep(),
            cards.row(
                cards.secondary_btn("مزامنة الآن", self._open_sync_now),
                cards.secondary_btn("الأعمال المرتبطة", self._open_linked_list),
                cards.secondary_btn("ربط عمل", self._open_link_pick_work),
            ),
            cards.row(
                cards.secondary_btn("ربط تلقائي بالأسماء", self._open_auto_link),
                cards.secondary_btn("فك ربط", self._open_unlink_pick),
                cards.secondary_btn("تسمية عربية", self._open_rename_pick),
            ),
            cards.row(
                cards.secondary_btn("قناة الإعلانات", self._open_channel_pick),
                cards.secondary_btn("إيقاف النظام" if en else "تشغيل النظام", self._toggle_enabled),
                cards.secondary_btn("إضافة تلقائية: " + ("مفعلة" if auto else "معطلة"), self._toggle_auto_add),
            ),
            cards.row(
                cards.secondary_btn("إعلانات: " + ("مفعلة" if ann else "معطلة"), self._toggle_announcements),
                cards.secondary_btn("مدة المزامنة", self._open_interval_set),
                cards.secondary_btn("رابط الفريق", self._open_team_slug_set),
            ),
        ]
        children += self._back_row()
        children += [cards.text(f"-# {cards.BOT_SIGNATURE}")]
        return children

    # ══════════════════════════════════════════════════════════
    # 1) مزامنة الآن
    # ══════════════════════════════════════════════════════════
    async def _open_sync_now(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            result = await run_sync_cycle(bot, manual=True)
        except Exception as e:
            await interaction.message.edit(view=cards.error_card(
                "فشلت المزامنة",
                [f"رسالة الخطأ:\n`{str(e)[:300]}`",
                 "إن كانت رسالة قاعدة بيانات فاستخدم /تشخيص لمعرفة السبب بدقة."],
                avatar_url=_bot_avatar()))
            return
        if not result.get("ok"):
            await interaction.message.edit(view=cards.error_card(
                "فشلت المزامنة",
                [f"**السبب:** {result.get('error', '—')}",
                 "سيعاد المحاولة تلقائيًا في الدورة التالية — البيانات الحالية سليمة."],
                avatar_url=_bot_avatar()))
            return
        if result.get("baseline"):
            self.mode = "hub"
            await self._show_after_defer(
                interaction,
                f"أُسِّس خط الأساس: **{result.get('baseline_count', 0)}** عمل من أعمال الفريق "
                "سُجّلوا معروفين **دون إضافتهم للبوت** — كما هو مطلوب.\n"
                "من الآن: كل عمل **جديد** يُكتشف ويُضاف تلقائيًا (إن كانت الإضافة التلقائية مفعلة)، "
                "وكل فصل **جديد** يُعلَن في قناة الإعلانات.")
            return
        lines = [
            f"**الفريق:** {result.get('team_name', '—')}",
            f"**أعمال الفريق المكتشفة:** {result.get('team_works', 0)}",
            f"**أعمال أُضيفت للبوت الآن:** {result.get('auto_added', 0)}",
            f"**فصول أُعلن عنها:** {result.get('announced', 0)}",
            f"**كاش فصول مُحدَّث:** {result.get('refreshed', 0)}",
        ]
        if result.get("rebaseline") is not None:
            lines.append(
                f"**فهرس أعمال الفريق اكتمل لأول مرة:** سُجّل {result['rebaseline']} عملًا "
                "إضافيًا معروفًا **دون إضافتها للبوت** — اربط ما تريد منها من زر «ربط عمل».")
        if result.get("backfilled") is not None:
            lines.append(
                f"**دفعة توسّع فهرس:** {result['backfilled']} عملًا سُجّلوا معروفين "
                "دون إضافة تلقائية احتياطًا — اربطها يدويًا متى شئت.")
        if result.get("errors"):
            lines.append("**ملاحظات:**")
            lines.extend(f"• {cards.clamp(e, 180)}" for e in result["errors"][:4])
        self.mode = "hub"
        await self._show_after_defer(interaction, "\n".join(lines))

    # ══════════════════════════════════════════════════════════
    # 2) الأعمال المرتبطة
    # ══════════════════════════════════════════════════════════
    async def _open_linked_list(self, interaction: discord.Interaction):
        self.mode = "linked_list"
        self.page = 0
        await self._show(interaction)

    async def _linked_children(self) -> list:
        works = await load_works()
        linked = [w for w in works if w.get("azora")]
        children = [cards.header(["## الأعمال المرتبطة بأزورا",
                                  f"{len(linked)} عمل مرتبط"], _bot_avatar()), cards.sep(2)]
        if not linked:
            children.append(cards.text(
                "لا توجد أعمال مرتبطة بعد — استخدم زر **ربط عمل** (ضغطتان على سيلكت) "
                "أو **ربط تلقائي بالأسماء**."))
        else:
            chapters_cache = await store.load_chapters_cache()
            team_cache = (await store.load_cache())["works"]
            page_items, total_pages = _page_of(linked, self.page, self.PER_PAGE)
            for w in page_items:
                link = w["azora"]
                cached = chapters_cache.get(link["slug"]) or {}
                count = cached.get("count")
                source_note = ""
                if count is None:
                    # الكاش الرقمي لم يُجلب بعد — نعرض عدد الفريق الورقي إن وجد
                    count = (team_cache.get(link["slug"]) or {}).get("chapter_count")
                    source_note = " (من كاش الفريق — الرقمي يُجلب بالمزامنة)" if count is not None else ""
                children.append(cards.text(
                    f"**{w.get('name')}**\n"
                    f"-# أزورا: `{link['slug']}` • الفصول المنشورة: {count if count is not None else '—'}{source_note} • "
                    f"ارتبط {_fmt_ago(link.get('linked_at'))}"))
            children.append(cards.sep())
            children.append(cards.pager_row(self.page, total_pages,
                                            self._prev_page, self._next_page))
        children += [cards.sep(),
                     cards.row(cards.secondary_btn("عودة إلى أزورا", self._back_to_hub, emoji="↩")),
                     cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
        return children

    # ══════════════════════════════════════════════════════════
    # 3) ربط عمل — سيلكت فقط
    # ══════════════════════════════════════════════════════════
    async def _open_link_pick_work(self, interaction: discord.Interaction):
        self.mode = "link_pick_work"
        self.page = 0
        self.pending_link_work = None
        self.pending_link_slug = None
        await self._show(interaction)

    def _suggest_rank(self, bot_name: str, azora_title: str) -> int:
        """0 = مطابقة تامة بعد التطبيع، 1 = احتواء، 2 = بلا اقتراح."""
        a, b = normalize_name(bot_name), normalize_name(azora_title)
        if not a or not b:
            return 2
        if a == b:
            return 0
        if a in b or b in a:
            return 1
        return 2

    async def _link_pick_work_children(self) -> list:
        works = await load_works()
        cache = await store.load_cache()
        unlinked = [w for w in works if not w.get("azora")]

        def suggestion(w):
            best = 2
            for _slug, entry in cache["works"].items():
                best = min(best, self._suggest_rank(w.get("name", ""), entry.get("title_en", "")))
            return best

        unlinked.sort(key=suggestion)
        page_items, total_pages = _page_of(unlinked, self.page, 25)
        children = [cards.header(["## ربط عمل بأزورا",
                                  "الخطوة 1 من 2 — اختر عمل البوت غير المرتبط."],
                                 _bot_avatar()), cards.sep(2)]
        if not unlinked:
            children.append(cards.text("كل الأعمال مرتبطة أصلًا أو لا توجد أعمال في القائمة."))
        elif not cache["works"]:
            children.append(cards.text(
                "قائمة أعمال الفريق فارغة بعد — نفّذ **مزامنة الآن** أولًا حتى تُبنى."))
        else:
            star = {0: "★ مطابقة — ", 1: "☆ قريب — "}
            options = []
            for w in page_items:
                prefix = star.get(suggestion(w), "")
                options.append(discord.SelectOption(
                    label=cards.clamp(prefix + w.get("name", ""), 100),
                    value=w.get("name", ""), emoji="📖"))
            children.append(cards.make_select("اختر عمل البوت...", options, self._link_work_picked))
            if total_pages > 1:
                children += [cards.sep(),
                             cards.pager_row(self.page, total_pages, self._prev_page, self._next_page)]
        children += [cards.sep(),
                     cards.row(cards.secondary_btn("عودة إلى أزورا", self._back_to_hub, emoji="↩")),
                     cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
        return children

    async def _link_work_picked(self, interaction: discord.Interaction):
        name = interaction.data["values"][0]
        works = await load_works()
        work = next((w for w in works if w.get("name") == name), None)
        if not work:
            await self._show(interaction, f"العمل **{name}** لم يعد موجودًا — أعد المحاولة.")
            return
        self.pending_link_work = work
        self.mode = "link_pick_azora"
        self.page = 0
        await self._show(interaction)

    async def _link_pick_azora_children(self) -> list:
        cache = await store.load_cache()
        works = await load_works()
        linked_slugs = {(w.get("azora") or {}).get("slug") for w in works if w.get("azora")}
        bot_name = (self.pending_link_work or {}).get("name", "")
        candidates = []
        for slug, entry in cache["works"].items():
            rank = self._suggest_rank(bot_name, entry.get("title_en", ""))
            candidates.append((rank, slug, entry))
        candidates.sort(key=lambda t: (t[0], str(t[2].get("title_en", "")).lower()))
        page_items, total_pages = _page_of(candidates, self.page, 25)
        children = [
            cards.header(["## ربط عمل بأزورا",
                          f"الخطوة 2 من 2 — عمل أزورا المقابل لـ **{bot_name}**."],
                         _bot_avatar()),
            cards.sep(2),
            cards.text("الاقتراحات تظهر أولًا (★ مطابقة، ☆ قريب) — والأعمال المرتبطة "
                       "بأعمال أخرى محجوبة من القائمة."),
            cards.sep(),
        ]
        if not page_items:
            children.append(cards.text("لا توجد أعمال متاحة في هذه الصفحة."))
        else:
            star = {0: "★ ", 1: "☆ "}
            options = []
            for rank, slug, entry in page_items:
                taken = " (مرتبط)" if slug in linked_slugs else ""
                options.append(discord.SelectOption(
                    label=cards.clamp(f"{star.get(rank, '')}{entry.get('title_en', slug)}{taken}", 100),
                    value=slug))
            children.append(cards.make_select("اختر عمل أزورا...", options, self._link_azora_picked))
            if total_pages > 1:
                children += [cards.sep(),
                             cards.pager_row(self.page, total_pages, self._prev_page, self._next_page)]
        children += [cards.sep(),
                     cards.row(cards.secondary_btn("رجوع", self._link_back_to_pick, emoji="↩"),
                               cards.secondary_btn("عودة إلى أزورا", self._back_to_hub)),
                     cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
        return children

    async def _link_back_to_pick(self, interaction: discord.Interaction):
        self.mode = "link_pick_work"
        self.page = 0
        await self._show(interaction)

    async def _link_azora_picked(self, interaction: discord.Interaction):
        self.pending_link_slug = interaction.data["values"][0]
        self.mode = "link_confirm"
        await self._show(interaction)

    async def _link_confirm_children(self) -> list:
        cache = await store.load_cache()
        entry = cache["works"].get(self.pending_link_slug or "") or {}
        work = self.pending_link_work or {}
        cover = entry.get("cover") or ""
        children: list = []
        head = ["## تأكيد الربط", f"**{work.get('name')}**"]
        children.append(cards.header(head, cover if cover else _bot_avatar()))
        children += [
            cards.sep(2),
            cards.text(
                f"**اسم العمل بالبوت:** {work.get('name')}\n"
                f"**العمل على أزورا:** {entry.get('title_en', self.pending_link_slug)}\n"
                f"**الرابط:** {client.AZORA_BASE}/series/{self.pending_link_slug}\n"
                f"**عدد الفصول الحالي على أزورا:** {entry.get('chapter_count', '—')}"
            ),
            cards.sep(),
            cards.text("بعد الربط: التسجيل في هذا العمل يقتصر على الفصول **المنشورة فعليًا** "
                       "على أزورا، ولا يُسمح بنفس الفصل والتخصص لشخصين.\n"
                       "سجلاتكم الحالية لا تُمسّ بشيء."),
            cards.sep(),
            cards.row(
                cards.success_btn("تأكيد الربط", self._link_commit),
                cards.secondary_btn("رجوع", self._link_back_to_azora, emoji="↩"),
                cards.secondary_btn("إلغاء", self._back_to_hub),
            ),
            cards.sep(),
            cards.text(f"-# {cards.BOT_SIGNATURE}"),
        ]
        return children

    async def _link_back_to_azora(self, interaction: discord.Interaction):
        self.mode = "link_pick_azora"
        self.page = 0
        await self._show(interaction)

    async def _link_commit(self, interaction: discord.Interaction):
        if not self.pending_link_work or not self.pending_link_slug:
            await self._show(interaction, "انتهت صلاحية الاختيار — أعد خطوات الربط.")
            return
        await interaction.response.defer()
        works = await load_works()
        work = next((w for w in works if w.get("name") == self.pending_link_work.get("name")), None)
        if not work:
            await interaction.message.edit(view=cards.error_card(
                "تعذر الربط", ["العمل لم يعد موجودًا في القائمة."], avatar_url=_bot_avatar()))
            return
        slug = self.pending_link_slug
        other = next((w for w in works if (w.get("azora") or {}).get("slug") == slug), None)
        if other:
            await interaction.message.edit(view=cards.error_card(
                "تعذر الربط",
                [f"عمل أزورا `{slug}` مرتبط أصلًا بعمل آخر: **{other.get('name')}**.",
                 "افصل ربطه أولًا إن أردت إعادة الربط."], avatar_url=_bot_avatar()))
            return
        cache = await store.load_cache()
        entry = cache["works"].get(slug) or {}
        note = await _link_work(work, slug, entry,
                                self.user.display_name if self.user else "admin")
        ok = await save_works(works)
        if not ok:
            await interaction.message.edit(view=cards.error_card(
                "تعذر الحفظ",
                ["قاعدة البيانات غير متاحة — لم يُحفظ الربط، أعد المحاولة."],
                avatar_url=_bot_avatar()))
            return
        self.mode = "hub"
        await self._show_after_defer(interaction,
                                     f"ارتبط **{work.get('name')}** بـ `{slug}` بنجاح.\n{note}")

    # ══════════════════════════════════════════════════════════
    # 4) ربط تلقائي بالأسماء
    # ══════════════════════════════════════════════════════════
    async def _open_auto_link(self, interaction: discord.Interaction):
        await interaction.response.defer()
        works = await load_works()
        cache = await store.load_cache()
        if not cache["works"]:
            await interaction.message.edit(view=cards.error_card(
                "لا يمكن الربط التلقائي",
                ["قائمة أعمال الفريق فارغة — نفّذ **مزامنة الآن** أولًا."],
                avatar_url=_bot_avatar()))
            return
        taken_slugs = {(w.get("azora") or {}).get("slug") for w in works if w.get("azora")}
        linked_lines: list = []
        for w in works:
            if w.get("azora"):
                continue
            norm = normalize_name(w.get("name", ""))
            if not norm:
                continue
            match = None
            for slug, entry in cache["works"].items():
                if slug in taken_slugs:
                    continue
                if normalize_name(entry.get("title_en", "")) == norm:
                    match = (slug, entry)
                    break
            if match:
                slug, entry = match
                note = await _link_work(w, slug, entry,
                                        self.user.display_name if self.user else "auto")
                taken_slugs.add(slug)
                linked_lines.append(f"**{w.get('name')}** ← `{slug}`\n-# {cards.clamp(note, 120)}")
        saved = await save_works(works) if linked_lines else True
        await log_audit("ربط_أزورا_تلقائي", 0, None, f"ارتبط {len(linked_lines)} عملًا بالأسماء")
        if not linked_lines:
            await interaction.message.edit(view=cards.info_card(
                "لا مطابقات تامة",
                ["لم أجد أعمالًا غير مرتبطة اسمها مطابق تمامًا لعمل على أزورا.",
                 "الأسماء العربية لن تطابق الإنجليزية — استخدم **ربط عمل**: "
                 "ضغطتان على قائمتين منسدلتين وخلاص."],
                avatar_url=_bot_avatar()))
            return
        if not saved:
            await interaction.message.edit(view=cards.error_card(
                "تعذر الحفظ", ["قاعدة البيانات غير متاحة — أعد المحاولة."],
                avatar_url=_bot_avatar()))
            return
        self.mode = "hub"
        await self._show_after_defer(interaction,
                                     "أُتمّ الربط التلقائي:\n" + "\n".join(linked_lines[:8]))

    # ══════════════════════════════════════════════════════════
    # 5) فك ربط
    # ══════════════════════════════════════════════════════════
    async def _open_unlink_pick(self, interaction: discord.Interaction):
        self.mode = "unlink_pick"
        self.page = 0
        await self._show(interaction)

    async def _unlink_pick_children(self) -> list:
        works = await load_works()
        linked = [w for w in works if w.get("azora")]
        children = [cards.header(["## فك ربط عمل",
                                  "اختر العمل المرتبط الذي تريد فصله عن أزورا."],
                                 _bot_avatar()), cards.sep(2)]
        if not linked:
            children.append(cards.text("لا توجد أعمال مرتبطة."))
        else:
            page_items, total_pages = _page_of(linked, self.page, 25)
            options = [discord.SelectOption(
                label=cards.clamp(f"{w.get('name', '')} — {w['azora']['slug']}", 100),
                value=w.get("name", ""), emoji="🔗")
                for w in page_items]
            children.append(cards.make_select("اختر العمل...", options, self._unlink_picked))
            if total_pages > 1:
                children.append(cards.sep())
                children.append(cards.pager_row(self.page, total_pages,
                                                self._prev_page, self._next_page))
        children += [cards.sep(),
                     cards.row(cards.secondary_btn("عودة إلى أزورا", self._back_to_hub, emoji="↩")),
                     cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
        return children

    async def _unlink_picked(self, interaction: discord.Interaction):
        name = interaction.data["values"][0]
        works = await load_works()
        work = next((w for w in works if w.get("name") == name), None)
        if not work:
            await self._show(interaction, f"العمل **{name}** لم يعد موجودًا.")
            return
        self.pending_unlink = work
        self.mode = "unlink_confirm"
        await self._show(interaction)

    async def _unlink_confirm_children(self) -> list:
        work = self.pending_unlink or {}
        link = work.get("azora") or {}
        children = [
            cards.header(["## تأكيد فك الربط", f"**{work.get('name')}**"], _bot_avatar()),
            cards.sep(2),
            cards.text(
                f"**الرابط الحالي:** `{link.get('slug', '—')}`\n"
                "**ما يحدث بعد الفك:**\n"
                "• العمل يبقى في البوت بكل سجلاته — لا يُحذف شيء.\n"
                "• تُرفع قيود أزورا عنه ويعود سلوكه القديم بالضبط.\n"
                "• لن يُعلَن عن فصوله الجديدة حتى إعادة الربط."
            ),
            cards.sep(),
            cards.row(
                cards.secondary_btn("تأكيد فك الربط", self._unlink_commit),
                cards.secondary_btn("إلغاء", self._back_to_hub),
            ),
            cards.sep(),
            cards.text(f"-# {cards.BOT_SIGNATURE}"),
        ]
        return children

    async def _unlink_commit(self, interaction: discord.Interaction):
        work = self.pending_unlink or {}
        await interaction.response.defer()
        works = await load_works()
        target = next((w for w in works if w.get("name") == work.get("name")), None)
        if not target or not target.get("azora"):
            await interaction.message.edit(view=cards.error_card(
                "تعذر الفك", ["العمل أو ربطه غير موجود."], avatar_url=_bot_avatar()))
            return
        slug = target["azora"].get("slug")
        del target["azora"]
        if not await save_works(works):
            await interaction.message.edit(view=cards.error_card(
                "تعذر الحفظ", ["قاعدة البيانات غير متاحة — لم يتغير شيء."],
                avatar_url=_bot_avatar()))
            return
        await store.delete_chapters_entry(slug or "")
        await log_audit("فك_ربط_أزورا", 0, None, f"فُك ربط {target.get('name')} عن {slug}")
        self.mode = "hub"
        await self._show_after_defer(
            interaction,
            f"فُك ربط **{target.get('name')}** عن `{slug}` — العمل وسجلاته كما هي بلا قيود أزورا.")

    # ══════════════════════════════════════════════════════════
    # 6) تسمية عربية + ترحيل السجلات
    # ══════════════════════════════════════════════════════════
    async def _open_rename_pick(self, interaction: discord.Interaction):
        self.mode = "rename_pick"
        self.page = 0
        await self._show(interaction)

    async def _rename_pick_children(self) -> list:
        works = await load_works()
        ordered = sorted(works, key=lambda w: (0 if w.get("azora") else 1, str(w.get("name", ""))))
        page_items, total_pages = _page_of(ordered, self.page, 25)
        children = [cards.header(
            ["## تسمية عربية لعمل",
             "الاسم المعروض في كل الأوامر والإعلانات — اكتب الاسم العربي وسيسجل "
             "الاسم الإنجليزي في بيانات الربط."],
            _bot_avatar()), cards.sep(2)]
        if not ordered:
            children.append(cards.text("لا توجد أعمال بعد."))
        else:
            options = [discord.SelectOption(
                label=cards.clamp(w.get("name", ""), 100), value=w.get("name", ""), emoji="✏️")
                for w in page_items]
            children.append(cards.make_select("اختر العمل...", options, self._rename_picked))
            if total_pages > 1:
                children += [cards.sep(),
                             cards.pager_row(self.page, total_pages, self._prev_page, self._next_page)]
        children += [cards.sep(),
                     cards.row(cards.secondary_btn("عودة إلى أزورا", self._back_to_hub, emoji="↩")),
                     cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
        return children

    async def _rename_picked(self, interaction: discord.Interaction):
        name = interaction.data["values"][0]
        works = await load_works()
        work = next((w for w in works if w.get("name") == name), None)
        if not work:
            await self._show(interaction, f"العمل **{name}** لم يعد موجودًا.")
            return
        self.pending_rename = work
        self.mode = "rename_wait"
        await self._show(interaction)
        # انتظار الاسم الجديد من نفس العضو بنفس القناة
        try:
            msg = await bot.wait_for(
                "message", check=self._wait_check(interaction.user.id, interaction.channel_id),
                timeout=120)
        except asyncio.TimeoutError:
            await self._wait_timed_out(interaction, "خطوة التسمية")
            return
        new_name = msg.content.strip()[:60]
        try:
            await msg.delete()
        except Exception:
            pass
        if not new_name:
            self.mode = "hub"
            await self.rebuild_async("لم يتم تغيير الاسم — القيمة فارغة.")
            await interaction.message.edit(view=self)
            return
        works = await load_works()
        target = next((w for w in works if w.get("name") == name), None)
        if not target:
            self.mode = "hub"
            await self.rebuild_async(f"العمل **{name}** لم يعد موجودًا.")
            await interaction.message.edit(view=self)
            return
        if any(w.get("name") == new_name for w in works):
            self.mode = "hub"
            await self.rebuild_async(f"الاسم **{new_name}** مستخدم بعمل آخر — لم يتغير شيء.")
            await interaction.message.edit(view=self)
            return
        old = target.get("name")
        target["name"] = new_name
        records = await load_records()
        migrated = 0
        for _uid, entries in records.items():
            for e in entries:
                if e.get("work_name") == old:
                    e["work_name"] = new_name
                    migrated += 1
        saved_works = await save_works(works)
        saved_records = True
        if migrated:
            from helpers.core import save_records
            saved_records = await save_records(records)
        await log_audit("تسمية_أزورا", 0, None, f"«{old}» ← «{new_name}» (سجلات مُرحّلة: {migrated})")
        if not saved_works or not saved_records:
            self.mode = "hub"
            await self.rebuild_async("تعذر الحفظ — قاعدة البيانات غير متاحة، لم يتغير شيء.")
            await interaction.message.edit(view=self)
            return
        self.mode = "hub"
        await self.rebuild_async(
            f"أُعيدت تسمية **{old}** إلى **{new_name}**.\n"
            f"سجلات مُرحّلة للاسم الجديد: {migrated} — كل الحسابات سليمة.")
        await interaction.message.edit(view=self)

    async def _rename_wait_children(self) -> list:
        work = self.pending_rename or {}
        link = work.get("azora") or {}
        children = [
            cards.header(["## تسمية عربية", f"**{work.get('name')}**"], _bot_avatar()),
            cards.sep(2),
            cards.text(
                "أرسل الاسم العربي الجديد في هذه القناة الآن (حتى 60 حرفًا).\n"
                f"**الاسم الإنجليزي المحفوظ في الربط:** {link.get('title_en') or '—'}\n"
                "سيُرحَّل كل سجلات العمل القديمة للاسم الجديد تلقائيًا حتى لا ينكسر أي حساب."
            ),
            cards.sep(),
            cards.row(cards.secondary_btn("إلغاء", self._back_to_hub)),
            cards.sep(),
            cards.text(f"-# لديك دقيقتان • {cards.BOT_SIGNATURE}"),
        ]
        return children

    # ══════════════════════════════════════════════════════════
    # 7) قناة الإعلانات
    # ══════════════════════════════════════════════════════════
    async def _open_channel_pick(self, interaction: discord.Interaction):
        self.mode = "channel_pick"
        await self._show(interaction)

    async def _channel_children(self) -> list:
        select = ui.ChannelSelect(
            placeholder="اختر قناة الإعلانات...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1, max_values=1,
        )
        select.callback = self._channel_picked
        children = [
            cards.header(["## قناة إعلانات نزول الفصول",
                          "كل فصل جديد لأعمال مرتبطة يُعلَن هنا فور اكتشافه بالمزامنة."],
                         _bot_avatar()),
            cards.sep(2),
            cards.text("اختر القناة من القائمة (قنوات النص فقط) — يمكنك كتابة اسمها داخلها للبحث."),
            cards.sep(),
            ui.ActionRow(select),
            cards.sep(),
            cards.row(cards.secondary_btn("عودة إلى أزورا", self._back_to_hub, emoji="↩")),
            cards.sep(),
            cards.text(f"-# {cards.BOT_SIGNATURE}"),
        ]
        return children

    async def _channel_picked(self, interaction: discord.Interaction):
        channel_id = int(interaction.data["values"][0])
        state = await store.load_state()
        state["announce_channel_id"] = channel_id
        if not await store.save_state(state):
            await self._show(interaction, "تعذر الحفظ — قاعدة البيانات غير متاحة.")
            return
        await log_audit("اعدادات_أزورا", 0, None, f"قناة الإعلانات ← {channel_id}")
        self.mode = "hub"
        await self._show(interaction,
                         f"قناة الإعلانات أصبحت <#{channel_id}> — ستظهر فيها إعلانات "
                         "الفصول الجديدة للأعمال المرتبطة فور نزولها.")

    # ══════════════════════════════════════════════════════════
    # 8) المفاتيح والمدة ورابط الفريق
    # ══════════════════════════════════════════════════════════
    async def _toggle_enabled(self, interaction: discord.Interaction):
        state = await store.load_state()
        state["enabled"] = not state.get("enabled", True)
        await store.save_state(state)
        await log_audit("اعدادات_أزورا", 0, None,
                        f"النظام ← {'مفعل' if state['enabled'] else 'متوقف'}")
        self.mode = "hub"
        await self._show(interaction)

    async def _toggle_auto_add(self, interaction: discord.Interaction):
        state = await store.load_state()
        state["auto_add_new_works"] = not state.get("auto_add_new_works", True)
        await store.save_state(state)
        self.mode = "hub"
        await self._show(interaction)

    async def _toggle_announcements(self, interaction: discord.Interaction):
        state = await store.load_state()
        state["announcements_enabled"] = not state.get("announcements_enabled", True)
        await store.save_state(state)
        self.mode = "hub"
        await self._show(interaction)

    async def _open_interval_set(self, interaction: discord.Interaction):
        self.mode = "interval_wait"
        await self._show(interaction)
        try:
            msg = await bot.wait_for(
                "message", check=self._wait_check(interaction.user.id, interaction.channel_id),
                timeout=120)
        except asyncio.TimeoutError:
            await self._wait_timed_out(interaction, "خطوة مدة المزامنة")
            return
        raw = msg.content.strip()
        try:
            await msg.delete()
        except Exception:
            pass
        if not raw.isdigit() or not (5 <= int(raw) <= 120):
            self.mode = "hub"
            await self.rebuild_async("قيمة غير صالحة — يجب عدد دقائق بين 5 و120، لم يتغير شيء.")
            await interaction.message.edit(view=self)
            return
        minutes = int(raw)
        state = await store.load_state()
        state["sync_interval_minutes"] = minutes
        await store.save_state(state)
        try:
            from azora.sync import azora_sync_loop
            if azora_sync_loop.is_running():
                azora_sync_loop.change_interval(minutes=minutes)
        except Exception:
            pass
        await log_audit("اعدادات_أزورا", 0, None, f"مدة المزامنة ← {minutes} دقيقة")
        self.mode = "hub"
        await self.rebuild_async(f"مدة المزامنة أصبحت كل **{minutes}** دقيقة (طبّقت فورًا).")
        await interaction.message.edit(view=self)

    async def _interval_wait_children(self) -> list:
        state = await store.load_state()
        children = [
            cards.header(["## مدة المزامنة",
                          f"الحالية: كل {state.get('sync_interval_minutes') or 10} دقيقة"],
                         _bot_avatar()),
            cards.sep(2),
            cards.text("أرسل عدد الدقائق في هذه القناة (من 5 إلى 120).\n"
                       "مدة أقصر = اكتشاف أسرع لنزول الفصول = طلبات أكثر على أزورا."),
            cards.sep(),
            cards.row(cards.secondary_btn("إلغاء", self._back_to_hub)),
            cards.sep(),
            cards.text(f"-# لديك دقيقتان • {cards.BOT_SIGNATURE}"),
        ]
        return children

    async def _open_team_slug_set(self, interaction: discord.Interaction):
        self.mode = "slug_wait"
        await self._show(interaction)
        try:
            msg = await bot.wait_for(
                "message", check=self._wait_check(interaction.user.id, interaction.channel_id),
                timeout=120)
        except asyncio.TimeoutError:
            await self._wait_timed_out(interaction, "خطوة رابط الفريق")
            return
        raw = msg.content.strip()
        try:
            await msg.delete()
        except Exception:
            pass
        new_slug = slug_from_input(raw)
        if not new_slug:
            self.mode = "hub"
            await self.rebuild_async("لم أفهم السلاغ — أعد خطوة رابط الفريق، لم يتغير شيء.")
            await interaction.message.edit(view=self)
            return
        await interaction.message.edit(view=cards.Card(cards.ACCENT_GOLD,
            cards.header(["## جارٍ التحقق من الفريق", f"`{new_slug}`"], _bot_avatar()),
            cards.sep(2), cards.text("أتحقق من صفحة الفريق على أزورا الآن…"),
            cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")))
        try:
            data = await client.fetch_team_page(new_slug, 1)
            team_name = str((data.get("team") or {}).get("name") or new_slug).upper()
        except client.AzoraError as e:
            self.mode = "hub"
            await self.rebuild_async(f"فشل التحقق من الفريق `{new_slug}` — لم يتغير شيء.\n"
                                     f"**السبب:** {e}")
            await interaction.message.edit(view=self)
            return
        state = await store.load_state()
        state["team_slug"] = new_slug
        state["team_id"] = data.get("team_id")
        state["team_name"] = team_name
        state["baseline_done"] = False  # فريق جديد = خط أساس جديد
        state["listing_v2"] = False     # فريق جديد = فهرس أعمال جديد من الصفر
        await store.save_state(state)
        await store.save_cache({"works": {}, "seen_chapter_ids": []})
        await log_audit("اعدادات_أزورا", 0, None, f"رابط الفريق ← {new_slug}")
        asyncio.create_task(_baseline_after_team_change())
        self.mode = "hub"
        await self.rebuild_async(
            f"الفريق أصبح **{team_name}** (`{new_slug}`) بعد تحقق ناجح.\n"
            "أُعد بناء خط الأساس تلقائيًا في الخلفية — أعمال الفريق الجديدة كلها "
            "ستُسجّل معروفة **دون إضافتها**، والجديد بعدها يُكتشف تلقائيًا.")
        await interaction.message.edit(view=self)

    async def _slug_wait_children(self) -> list:
        state = await store.load_state()
        current = state.get("team_slug") or client.DEFAULT_TEAM_SLUG
        children = [
            cards.header(["## تغيير رابط الفريق", f"الحالي: `{current}`"], _bot_avatar()),
            cards.sep(2),
            cards.text("أرسل السلاغ أو الرابط الكامل في هذه القناة.\n"
                       "**مثال:** `cookies` أو `https://azorafly.com/teams/cookies`\n"
                       "يتم التحقق من وجود الفريق قبل الحفظ، ثم يُبنى خط أساس جديد تلقائيًا."),
            cards.sep(),
            cards.row(cards.secondary_btn("إلغاء", self._back_to_hub)),
            cards.sep(),
            cards.text(f"-# لديك دقيقتان • {cards.BOT_SIGNATURE}"),
        ]
        return children


async def _baseline_after_team_change():
    """مزامنة خط أساس فورية بعد تغيير الفريق — في الخلفية."""
    try:
        result = await run_sync_cycle(bot, manual=True)
        print(f"[AZORA] خط أساس الفريق الجديد: {result}")
    except Exception as e:
        print(f"[AZORA] فشل خط الأساس بعد تغيير الفريق: {e}")


# ═══════════════════════════════════════════════════════════════
# الأمر نفسه — للمشرفين فقط (نفس صلاحية لوحة التحكم)
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="أزورا",
                  description="لوحة ربط أعمال الفريق على أزورا وتقييد التسجيل بالفصول المنشورة")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def azora_hub(interaction: discord.Interaction):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    if not channel_allowed(interaction):
        await interaction.response.send_message(
            view=cards.channel_card(SETTINGS.get("allowed_channels", []), avatar), ephemeral=True)
        return
    view = await AzoraHubView.create(interaction.guild, interaction.user)
    await interaction.response.send_message(view=view)
