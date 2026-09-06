from collections import defaultdict
import discord
from discord import app_commands
from discord import ui
from state import bot
from helpers.core import *
from ui import cards


# ═══════════════════════════════════════════════════════════════
# 🔧 أساس مشترك: LayoutView ديناميكي يبني حاوية ZEUS من جديد
#   عند كل تغيير صفحة — نفس سلوك تحرير البطاقة الواحدة في بوت السحب.
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


# ═══════════════════════════════════════════════════════════════
# 1️⃣ قائمة الأعمال — نفس نمط بطاقة /مواقع في بوت السحب
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
        self.works_info = works_info
        self.total_pages = max(1, (len(works_info) + self.per_page - 1) // self.per_page)
        self.rebuild()

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
                    f"{len(members)} أعضاء • {chapters} فصول • {self.currency}{total:.2f}", 100)
            ))
        return options

    async def select_callback(self, interaction: discord.Interaction):
        work_name = interaction.data['values'][0]
        members_info = [m for w, ms in self.works_info if w == work_name for m in ms]
        view = WorkMembersView(self, work_name, members_info)
        await interaction.response.edit_message(view=view)

    async def refresh_list(self, interaction: discord.Interaction):
        new_info = await get_works_info(self.guild)
        self.works_info = new_info
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
        children: list = [
            cards.header(
                ["## 🗂️ أعمال الفريق", f"**{len(self.works_info)}** أعمال متاحة."],
                avatar,
            ),
            cards.sep(2),
        ]
        page_items = self._options()
        if page_items:
            children.append(cards.text("-# اختر عملاً من القائمة لرؤية المساهمين وتفاصيلهم."))
            children.append(cards.sep())
            children.append(cards.make_select("اختر العمل...", page_items, self.select_callback))
        else:
            children.append(cards.text("لا توجد أعمال متاحة بعد — تُضاف الأعمال من /اضافة_عمل."))
        if self.total_pages > 1:
            children.append(cards.sep())
            children.append(cards.pager_row(self.current_page, self.total_pages, self.prev_page, self.next_page))
        return children


class WorkMembersView(DynamicCardView):
    """أعضاء عمل محدد — ملخص + قائمة اختيار عضو + عودة إلى القائمة."""

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
            await interaction.response.send_message(
                view=cards.error_card("❌ لا توجد فصول",
                                      [f"لا توجد فصول للعضو {user_display} في عمل {self.work_name}."]),
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
            self.currency, back_view=self,
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
            cards.header([f"## 📖 {cards.clamp(self.work_name, 80)}",
                          f"**{len(self.members_info)}** أعضاء — **{total_chapters}** فصول — **{self.currency}{total_amount:.2f}**"],
                         avatar),
            cards.sep(2),
        ]
        start = self.current_page * self.per_page
        page_members = self.members_info[start:start + self.per_page]
        if page_members:
            preview_lines = []
            for member in page_members[:10]:
                preview_lines.append(f"• {member[1]} — {member[2]} فصول — {self.currency}{member[3]:.2f}")
            body = "\n".join(preview_lines)
            if len(self.members_info) > 10:
                body += f"\n-# و{len(self.members_info) - 10} عضوًا آخر في هذه الصفحة…"
            children.append(cards.text(body))
            children.append(cards.sep())
            options = [
                discord.SelectOption(
                    label=cards.clamp(m[1], 100),
                    value=str(m[0]),
                    description=cards.clamp(f"{m[2]} فصول • {self.currency}{m[3]:.2f}", 100),
                ) for m in page_members
            ]
            children.append(cards.make_select("اختر عضواً...", options, self.select_callback))
        else:
            children.append(cards.text("لا يوجد مساهمون في هذا العمل بعد."))
        if self.total_pages > 1:
            children.append(cards.sep())
            children.append(cards.pager_row(self.current_page, self.total_pages, self.prev_page, self.next_page))
        children.append(cards.sep())
        children.append(cards.row(
            cards.secondary_btn("عودة إلى النتائج", self.back_to_browse, emoji="↩")
        ))
        return children


class WorkDetailsView(DynamicCardView):
    """تفاصيل فصول عضو داخل عمل — 10 فصول/صفحة + عودة إلى الأعضاء."""

    def __init__(self, work_name, chapters_list, user_id, user_name, currency,
                 back_callback: callable = None, back_view=None):
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

    async def close_view(self, interaction: discord.Interaction):
        await interaction.response.defer()

    def build_children(self) -> list:
        avatar = self.avatar(self.guild if hasattr(self, "guild") else None)
        total_amount = sum(ch['total'] for ch in self.chapters_list)
        children: list = [
            cards.header(
                [f"## 📖 {cards.clamp(self.work_name, 80)}",
                 f"**{self.user_name}** — **{len(self.chapters_list)}** فصول — **{self.currency}{total_amount:.2f}**"],
                avatar,
            ),
            cards.sep(2),
        ]
        start = self.current_page * self.items_per_page
        page_chapters = self.chapters_list[start:start + self.items_per_page]
        lines = []
        for i, ch in enumerate(page_chapters, start + 1):
            note = f" | {ch.get('notes')}" if ch.get('notes') else ""
            lines.append(f"**{i}.** فصل {ch['chapter']} — {ch['type']} — {self.currency}{ch['total']:.2f}{note}")
        children.append(cards.text("\n".join(lines)))
        children.append(cards.sep())
        children.append(cards.text(f"-# إجمالي العمل: {self.currency}{total_amount:.2f} • صفحة {self.current_page + 1} من {self.total_pages}"))
        if self.total_pages > 1:
            children.append(cards.sep())
            children.append(cards.pager_row(self.current_page, self.total_pages, self.prev_page, self.next_page))
        children.append(cards.sep())
        back_btn = (cards.secondary_btn("عودة إلى الأعضاء", self.back_action, emoji="↩")
                    if (self.back_view is not None or self.back_callback is not None)
                    else cards.secondary_btn("عودة إلى الأعضاء", self.close_view, emoji="↩", disabled=True))
        children.append(cards.row(back_btn))
        return children


# ═══════════════════════════════════════════════════════════════
# توافق الأسماء القديمة — WorksPaginator كان الاسم المستخدم في
# reports.py؛ نجعله اسمًا لـ WorksBrowseView الجديدة.
# ═══════════════════════════════════════════════════════════════
WorksPaginator = WorksBrowseView
