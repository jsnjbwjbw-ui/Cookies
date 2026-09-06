from collections import defaultdict
import discord
from discord import app_commands
from discord import ui
from state import bot
from helpers.core import *
from ui import cards


# ═══════════════════════════════════════════════════════════════
# 🔧 أساس مشترك: LayoutView ديناميكي يبني حاوية Cookies Tracker
#   من جديد عند كل تغيير صفحة — نفس سلوك تحرير البطاقة الواحدة.
# ═══════════════════════════════════════════════════════════════
class DynamicCardView(ui.LayoutView):
    ACCENT = cards.ACCENT_GOLD
    TITLE = "بطاقة"
    INTRO = ""
    FOOTNOTES: tuple = ()

    def __init__(self, timeout: float = 300.0):
        super().__init__(timeout=timeout)

    # ── لكل صفقة فرعية: تبني children الحاوية ──
    def build_children(self) -> list:
        raise NotImplementedError

    def accent(self) -> int:
        return self.ACCENT

    def rebuild(self):
        self.clear_items()
        children = self.build_children()
        children.append(cards.sep())
        for note in self.FOOTNOTES:
            children.append(cards.text(note))
            children.append(cards.sep())
        children.append(cards.text(f"-# {cards.BOT_SIGNATURE}"))
        self.add_item(cards.container(self.accent(), *children))

    async def refresh(self, interaction: discord.Interaction):
        self.rebuild()
        await interaction.response.edit_message(view=self)

    def avatar(self, interaction_or_guild) -> str | None:
        b = bot.user
        return b.display_avatar.url if b else None


def _guild_member(guild: discord.Guild | None, user_id) -> discord.Member | None:
    """جلب العضو من الكاش (سريع) لاستخدام صورته في البطاقات."""
    if guild is None:
        return None
    try:
        return guild.get_member(int(user_id))
    except (ValueError, TypeError):
        return None


# ═══════════════════════════════════════════════════════════════
# 1️⃣ قائمة الأعمال — مرتبة من الأكثر نشاطًا إلى الأقل
# ═══════════════════════════════════════════════════════════════
async def get_works_info(guild: discord.Guild):
    """Build list of works with their contributors."""
    approved_works = await load_works()
    records = await load_records()
    isolated = get_isolated_work_names(approved_works)

    contrib_map = defaultdict(lambda: defaultdict(lambda: {"count": 0, "total": 0.0, "types": defaultdict(int)}))
    for user_id_str, entries in records.items():
        for entry in entries:
            work = entry.get("work_name")
            if work and work not in isolated:
                info = contrib_map[work][user_id_str]
                info["count"] += 1
                info["total"] += entry.get("total", 0)
                info["types"][entry.get("work_type", "غير محدد")] += 1

    works_info = []
    for w in approved_works:
        if is_work_isolated(w):
            continue
        work_name = w["name"]
        contributors = contrib_map.get(work_name, {})
        members_list = []
        for uid_str, member_stats in contributors.items():
            uid = int(uid_str)
            username_hint = None
            if uid_str in records:
                for e in records[uid_str]:
                    if e.get("username"):
                        username_hint = e["username"]
                        break
            display = format_member_display(guild, uid, username_hint)
            members_list.append((uid, display, member_stats["count"], member_stats["total"], dict(member_stats["types"])))
        members_list.sort(key=lambda item: (item[2], item[3]), reverse=True)
        works_info.append((work_name, members_list))
    return works_info


class WorksBrowseView(DynamicCardView):
    """قائمة الأعمال + قائمة منسدلة لاختيار العمل (24/صفحة) + تنقل."""

    def __init__(self, works_info, guild):
        super().__init__(timeout=300.0)
        self.guild = guild
        self.currency = SETTINGS.get('currency', '$') or '$'
        self.per_page = 24
        self.current_page = 0
        # الأكثر فصولًا أولًا — الأعمال النشطة تظهر دائمًا في المقدمة
        self.works_info = sorted(works_info, key=lambda w: sum(m[2] for m in w[1]), reverse=True)
        self.total_pages = max(1, (len(self.works_info) + self.per_page - 1) // self.per_page)
        self.rebuild()

    def _totals(self):
        total_ch = sum(m[2] for _, ms in self.works_info for m in ms)
        total_amt = sum(m[3] for _, ms in self.works_info for m in ms)
        return total_ch, total_amt

    def _options(self):
        start = self.current_page * self.per_page
        page_works = self.works_info[start:start + self.per_page]
        options = []
        for work_name, members in page_works:
            chapters = sum(m[2] for m in members) if members else 0
            total = sum(m[3] for m in members) if members else 0
            options.append(discord.SelectOption(
                label=cards.clamp(work_name, 100),
                value=work_name,
                description=cards.clamp(
                    f"{len(members)} أعضاء • {chapters} فصول • {self.currency}{total:,.2f}", 100)
            ))
        return options

    async def select_callback(self, interaction: discord.Interaction):
        work_name = interaction.data['values'][0]
        members_info = [m for w, ms in self.works_info if w == work_name for m in ms]
        view = WorkMembersView(self, work_name, members_info)
        await interaction.response.edit_message(view=view)

    async def refresh_list(self, interaction: discord.Interaction):
        new_info = await get_works_info(self.guild)
        self.works_info = sorted(new_info, key=lambda w: sum(m[2] for m in w[1]), reverse=True)
        self.current_page = 0
        self.total_pages = max(1, (len(new_info) + self.per_page - 1) // self.per_page)
        await self.refresh(interaction)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        await self.refresh(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        await self.refresh(interaction)

    def build_children(self) -> list:
        avatar = self.avatar(self.guild)
        total_ch, total_amt = self._totals()
        children: list = [
            cards.header(
                ["## 🗂️ أعمال الفريق",
                 f"**{len(self.works_info)}** أعمال — 📑 **{total_ch}** فصول — 💵 **{self.currency}{total_amt:,.2f}**"],
                avatar,
            ),
            cards.sep(2),
        ]
        page_items = self._options()
        if page_items:
            children.append(cards.text("-# اختر عملاً من القائمة لرؤية مساهميه وتفاصيل فصولهم."))
            children.append(cards.sep())
            children.append(cards.make_select("اختر العمل...", page_items, self.select_callback))
        else:
            children.append(cards.text("لا توجد أعمال متاحة بعد — تُضاف الأعمال من /اضافة_عمل."))
        if self.total_pages > 1:
            children.append(cards.sep())
            children.append(cards.pager_row(self.current_page, self.total_pages, self.prev_page, self.next_page))
        return children


class WorkMembersView(DynamicCardView):
    """مساهمو عمل محدد — قائمة اختيار عضو (البيانات في وصف كل خيار)
    + عودة إلى القائمة. بلا نصوص مكررة فوق القائمة لراحة العين."""

    def __init__(self, browse: WorksBrowseView, work_name, members_info):
        super().__init__(timeout=300.0)
        self.browse = browse
        self.guild = browse.guild
        self.currency = browse.currency
        self.work_name = work_name
        self.members_info = members_info
        self.per_page = 24
        self.current_page = 0
        self.total_pages = max(1, (len(members_info) + self.per_page - 1) // self.per_page)
        self.rebuild()

    async def select_callback(self, interaction: discord.Interaction):
        user_id = int(interaction.data['values'][0])
        user_display = next((info[1] for info in self.members_info if info[0] == user_id), str(user_id))
        records = await load_records()
        isolated = get_isolated_work_names(await load_works())
        user_entries = records.get(str(user_id), [])
        work_entries = [e for e in user_entries if e.get("work_name") == self.work_name and e.get("work_name") not in isolated]
        if not work_entries:
            member_obj = _guild_member(self.guild, user_id)
            await interaction.response.send_message(
                view=cards.error_card("❌ لا توجد فصول",
                                      [f"لا توجد فصول للعضو {user_display} في عمل {self.work_name}."],
                                      avatar_url=_member_avatar_or_none(member_obj)),
                ephemeral=True)
            return
        chapters_details = [{
            "chapter": e.get("chapter"),
            "type": e.get("work_type"),
            "total": e.get("total", 0),
            "notes": e.get("notes", "")
        } for e in work_entries]
        view = WorkDetailsView(
            self.work_name, chapters_details, user_id, user_display,
            self.currency, back_view=self, guild=self.guild,
        )
        await interaction.response.edit_message(view=view)

    async def back_to_browse(self, interaction: discord.Interaction):
        await self.browse.refresh_list(interaction)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        await self.refresh(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        await self.refresh(interaction)

    def build_children(self) -> list:
        avatar = self.avatar(self.guild)
        total_chapters = sum(m[2] for m in self.members_info) if self.members_info else 0
        total_amount = sum(m[3] for m in self.members_info) if self.members_info else 0
        children: list = [
            cards.header([f"## 👥 مساهمو العمل",
                          f"**{cards.clamp(self.work_name, 60)}**\n"
                          f"**{len(self.members_info)}** أعضاء — 📑 **{total_chapters}** فصول — 💵 **{self.currency}{total_amount:,.2f}**"],
                         avatar),
            cards.sep(2),
        ]
        start = self.current_page * self.per_page
        page_members = self.members_info[start:start + self.per_page]
        if page_members:
            # المرتبون الثلاثة الأوائل يظهرون كسطر سريع تحت الرأس
            podium = "\n".join(
                f"{'🥇' if k == 1 else '🥈' if k == 2 else '🥉'} {m[1]} — 📑 {m[2]} فصول — 💵 {self.currency}{m[3]:,.2f}"
                for k, m in enumerate(page_members[:3], 1)
            )
            children.append(cards.text(f"**الأعلى مساهمة في هذا العمل**\n{podium}"))
            children.append(cards.sep())
            options = [
                discord.SelectOption(
                    label=cards.clamp(m[1].lstrip('@'), 100),
                    value=str(m[0]),
                    description=cards.clamp(f"📑 {m[2]} فصول • 💵 {self.currency}{m[3]:,.2f}", 100),
                ) for m in page_members
            ]
            children.append(cards.make_select("اختر عضواً لعرض فصوله بالتفصيل...", options, self.select_callback))
        else:
            children.append(cards.text("لا يوجد مساهمون في هذا العمل بعد."))
        if self.total_pages > 1:
            children.append(cards.sep())
            children.append(cards.pager_row(self.current_page, self.total_pages, self.prev_page, self.next_page))
        children.append(cards.sep())
        children.append(cards.row(
            cards.secondary_btn("عودة إلى الأعمال", self.back_to_browse, emoji="↩")
        ))
        return children


def _member_avatar_or_none(member) -> str | None:
    try:
        return member.display_avatar.url if member else None
    except Exception:
        return None


class WorkDetailsView(DynamicCardView):
    """تفاصيل فصول عضو داخل عمل — الترتيب الجديد المقروء:
    1️⃣ الملخص الرقمي → 2️⃣ التوزيع على التخصصات (بأشرطة) →
    3️⃣ قائمة الفصول مرتبة رقميًا من الأقدم — ثم التنقل والعودة.
    الصورة المصغرة لصورة العضو المعنيّ."""

    def __init__(self, work_name, chapters_list, user_id, user_name, currency,
                 back_callback: callable = None, back_view=None, guild: discord.Guild | None = None):
        super().__init__(timeout=300.0)
        self.work_name = work_name
        self.chapters_list = chapters_list
        self.user_id = user_id
        self.user_name = user_name
        self.currency = currency or '$'
        self.current_page = 0
        self.items_per_page = 10
        self.total_pages = max(1, (len(chapters_list) + self.items_per_page - 1) // self.items_per_page)
        self.back_callback = back_callback
        self.back_view = back_view
        self.guild = guild
        self.rebuild()

    async def back_action(self, interaction: discord.Interaction):
        if self.back_view is not None:
            await interaction.response.edit_message(view=self.back_view)
        elif self.back_callback is not None:
            await self.back_callback(interaction)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        await self.refresh(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        await self.refresh(interaction)

    def _summary_block(self) -> str:
        total_amount = sum(ch['total'] for ch in self.chapters_list)
        count = len(self.chapters_list)
        avg = (total_amount / count) if count else 0
        return ("### 📊 الملخص\n"
                f"**📑 الفصول:** {count} • **💵 المجموع:** {self.currency}{total_amount:,.2f} • "
                f"**💰 متوسط الفصل:** {self.currency}{avg:,.2f}")

    def _types_block(self) -> str | None:
        stats = defaultdict(lambda: {"c": 0, "t": 0.0})
        for ch in self.chapters_list:
            s = stats[ch.get('type', 'غير محدد')]
            s["c"] += 1
            s["t"] += ch.get('total', 0)
        if not stats:
            return None
        max_c = max(s["c"] for s in stats.values())
        lines = []
        for t, s in sorted(stats.items(), key=lambda kv: -kv[1]["c"]):
            bar = cards.progress_bar(s["c"], max_c)
            lines.append(f"• **{str(t).replace('_', ' ').title()}** — {bar} **{s['c']}** فصول — {self.currency}{s['t']:,.2f}")
        return "### 🛠️ التوزيع على التخصصات\n" + "\n".join(lines)

    def _chapters_block(self) -> str:
        ordered = sort_entries_by_chapter(self.chapters_list)
        start = self.current_page * self.items_per_page
        page = ordered[start:start + self.items_per_page]
        lines = []
        for ch in page:
            note = f"\n  -# 📝 {ch['notes']}" if ch.get('notes') else ""
            lines.append(f"• **فصل {ch['chapter']}** — {ch.get('type', 'غير محدد')} — {self.currency}{ch.get('total', 0):.2f}{note}")
        return "### 📑 الفصول\n" + "\n".join(lines)

    def build_children(self) -> list:
        member = _guild_member(self.guild, self.user_id)
        avatar = _member_avatar_or_none(member)
        who = member.mention if member else f"**{self.user_name}**"
        children: list = [
            cards.header(
                [f"## 📖 {cards.clamp(self.work_name, 60)}",
                 f"{who}\n📄 تفاصيل الفصول المسجلة في هذا العمل"],
                avatar,
            ),
            cards.sep(2),
        ]
        blocks = [self._summary_block()]
        types_block = self._types_block()
        if types_block:
            blocks.append(types_block)
        blocks.append(self._chapters_block())
        children.append(cards.text(cards.clamp("\n\n".join(blocks), 3600)))
        children.append(cards.sep())
        children.append(cards.text(
            f"-# الفصول مرتبة رقميًا • صفحة {self.current_page + 1} من {self.total_pages} • "
            f"إجمالي العمل: {self.currency}{sum(ch['total'] for ch in self.chapters_list):,.2f}"))
        if self.total_pages > 1:
            children.append(cards.sep())
            children.append(cards.pager_row(self.current_page, self.total_pages, self.prev_page, self.next_page))
        children.append(cards.sep())
        back_btn = (cards.secondary_btn("عودة إلى المساهمين", self.back_action, emoji="↩")
                    if (self.back_view is not None or self.back_callback is not None)
                    else cards.secondary_btn("عودة إلى المساهمين", None, emoji="↩", disabled=True))
        children.append(cards.row(back_btn))
        return children


# ═══════════════════════════════════════════════════════════════
# توافق الأسماء القديمة — WorksPaginator كان الاسم المستخدم في
# reports.py؛ نجعله اسمًا لـ WorksBrowseView الجديدة.
# ═══════════════════════════════════════════════════════════════
WorksPaginator = WorksBrowseView
