from datetime import datetime, timedelta
from collections import defaultdict
import discord
from discord import app_commands
from discord.ext import commands
from discord import ui
from state import bot
from helpers.core import *
from helpers.core import make_embed  # noqa: F401 (متاح للتوافق)
from views.paginators import WorksPaginator, get_works_info
from tasks.lifecycle import specialty_autocomplete
from ui import cards


def _bot_avatar():
    return bot.user.display_avatar.url if bot.user else None


def _member_avatar(member: discord.Member | None):
    return member.display_avatar.url if member else None


# ═══════════════════════════════════════════════════════════════
# 🎨 ملخص شغل عضو — بطاقة حية بقائمة أعمال منسدلة + تفاصيل
#   (نفس بنية بطاقات بوت السحب: رأس بصورة + فواصل + عودة ↩)
# ═══════════════════════════════════════════════════════════════
class WorkSummarySelectView(ui.LayoutView):
    def __init__(self, works, bonuses, deductions, member: discord.Member, user_id,
                 currency, title_prefix="📊 ملخص شغل"):
        super().__init__(timeout=300.0)
        self.works = works
        self.bonuses = bonuses
        self.deductions = deductions
        self.member = member
        self.user_id = user_id
        self.currency = currency or '$'
        self.title_prefix = title_prefix
        self.mode = "summary"      # summary | work | bonuses | all
        self.selected_work = None
        self.rebuild()

    # ── بناء الملخص ──
    def build_children(self) -> list:
        avatar = _member_avatar(self.member)
        if self.mode == "summary":
            return self._summary_children(avatar)
        if self.mode == "work":
            return self._work_children(self.selected_work, avatar)
        if self.mode == "bonuses":
            return self._bonuses_children(avatar)
        return self._all_children(avatar)

    def _summary_stats_lines(self):
        gross = sum(sum(e.get("total", 0) for e in entries) for entries in self.works.values())
        total_bonus = sum(e.get("total", 0) for e in self.bonuses)
        total_deduct = sum(abs(e.get("total", 0)) for e in self.deductions)
        net = gross + total_bonus - total_deduct
        total_works = len(self.works)
        total_chapters = sum(len(entries) for entries in self.works.values())
        lines = [
            f"**📁 عدد الأعمال:** {total_works}",
            f"**📑 إجمالي الفصول:** {total_chapters}",
            f"**💰 إجمالي الأعمال:** {self.currency}{gross:.2f}",
        ]
        if total_bonus:
            lines.append(f"**🎁 إجمالي المكافآت:** {self.currency}{total_bonus:.2f}")
        if total_deduct:
            lines.append(f"**🔻 إجمالي الخصومات:** {self.currency}{total_deduct:.2f}")
        lines.append(f"**💵 الصافي النهائي:** {self.currency}{net:.2f}")
        return lines

    def _summary_children(self, avatar):
        children: list = [
            cards.header([f"## {self.title_prefix} {self.member.display_name}"], avatar),
            cards.sep(2),
            cards.text("\n".join(self._summary_stats_lines())),
            cards.sep(),
        ]
        options = []
        for i, work_name in enumerate(sorted(self.works.keys())):
            if i >= 24:
                break
            chapters = len(self.works[work_name])
            options.append(discord.SelectOption(
                label=cards.clamp(work_name, 100), value=work_name,
                description=cards.clamp(f"{chapters} فصول", 100), emoji="📖"))
        if self.bonuses or self.deductions:
            options.append(discord.SelectOption(label="المكافآت والخصومات", value="__bonuses__",
                                                description="تفاصيل المكافآت والخصومات", emoji="⚖️"))
        if len(self.works) > 1:
            options.append(discord.SelectOption(label="عرض الكل", value="__all__",
                                                description="جميع الفصول مجمعة", emoji="📚"))
        if options:
            children.append(cards.text("-# اختر عملاً من القائمة لعرض التفاصيل."))
            children.append(cards.sep())
            children.append(cards.make_select("اختر عملاً لعرض التفاصيل...", options, self.select_callback))
        return children

    def _work_children(self, work_name, avatar):
        entries = self.works[work_name]
        total = sum(e.get("total", 0) for e in entries)
        count = len(entries)
        types_count = {}
        for e in entries:
            t = e.get("work_type", "غير محدد")
            types_count[t] = types_count.get(t, 0) + 1
        type_str = ", ".join(f"**{k.replace('_',' ').title()}:** {v}" for k, v in types_count.items() if v > 0)

        children: list = [
            cards.header([f"## 📖 {cards.clamp(work_name, 80)}",
                          f"**{count}** فصول — **{self.currency}{total:.2f}**"], avatar),
            cards.sep(2),
        ]
        body_lines = [f"**📊 التخصصات:** {type_str}"] if type_str else []
        lines = []
        for i, e in enumerate(entries, 1):
            ch = e.get("chapter", "؟")
            tp = e.get("work_type", "غير محدد")
            amt = e.get("total", 0)
            note = f" | {e.get('notes')}" if e.get("notes") else ""
            lines.append(f"**{i}.** فصل {ch} — {tp} — {self.currency}{amt:.2f}{note}")
        if lines:
            text_body = "\n".join(lines[:15])
            if len(lines) > 15:
                text_body += f"\n-# … و{len(lines) - 15} فصل إضافي"
            body_lines.append(text_body)
        children.append(cards.text("\n\n".join(body_lines)))
        children += [cards.sep(), self._back_row()]
        return children

    def _all_children(self, avatar):
        children: list = [
            cards.header([f"## 📚 جميع الفصول — {self.member.display_name}"], avatar),
            cards.sep(2),
        ]
        chunks = []
        for work_name, entries in self.works.items():
            total = sum(e.get("total", 0) for e in entries)
            cnt = len(entries)
            preview = [f"• {e.get('chapter','؟')} ({e.get('work_type','؟')}) {self.currency}{e.get('total',0):.2f}"
                       for e in entries[:5]]
            if len(entries) > 5:
                preview.append("-# … والمزيد")
            chunks.append(f"**📖 {work_name}** ({cnt} فصل — {self.currency}{total:.2f})\n" + "\n".join(preview))
        children.append(cards.text(cards.clamp("\n\n".join(chunks), 3400)))
        children += [cards.sep(), self._back_row()]
        return children

    def _bonuses_children(self, avatar):
        children: list = [
            cards.header(["## ⚖️ المكافآت والخصومات", f"**{self.member.display_name}**"], avatar),
            cards.sep(2),
        ]
        bon_lines = [f"🎁 {e.get('chapter','مكافأة')}: {self.currency}{e.get('total',0):.2f} — {e.get('notes','')}"
                     for e in self.bonuses] or ["لا يوجد"]
        ded_lines = [f"🔻 {e.get('chapter','خصم')}: {self.currency}{abs(e.get('total',0)):.2f} — {e.get('notes','')}"
                     for e in self.deductions] or ["لا يوجد"]
        children.append(cards.text("**المكافآت**\n" + "\n".join(bon_lines)))
        children.append(cards.sep())
        children.append(cards.text("**الخصومات**\n" + "\n".join(ded_lines)))
        children += [cards.sep(), self._back_row()]
        return children

    def _back_row(self):
        return cards.row(cards.secondary_btn("عودة إلى الملخص", self.back_callback, emoji="↩"))

    async def select_callback(self, interaction: discord.Interaction):
        selected = interaction.data['values'][0]
        if selected == "__all__":
            self.mode = "all"
        elif selected == "__bonuses__":
            self.mode = "bonuses"
        else:
            self.mode = "work"
            self.selected_work = selected
        await self.refresh(interaction)

    async def back_callback(self, interaction: discord.Interaction):
        self.mode = "summary"
        self.selected_work = None
        await self.refresh(interaction)

    def rebuild(self):
        self.clear_items()
        children = self.build_children()
        children.append(cards.sep())
        children.append(cards.text(f"-# {cards.BOT_SIGNATURE}"))
        self.add_item(cards.container(cards.ACCENT_GOLD, *children))

    async def refresh(self, interaction: discord.Interaction):
        self.rebuild()
        await interaction.response.edit_message(view=self)


# ═══════════════════════════════════════════════════════════════
# 📊 دوال الإحصائيات
# ═══════════════════════════════════════════════════════════════
def get_top_members_dict(stat_doc):
    """تحويل top_members إلى قاموس مهما كان شكلها (list/dict)"""
    data = stat_doc.get("top_members", {})
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        result = {}
        for item in data:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                result[str(item[0])] = item[1]
            elif isinstance(item, dict) and 'user_id' in item:
                result[str(item['user_id'])] = item
        return result
    return {}


async def build_top_card(guild: discord.Guild, currency, stat_doc, sort_by="amount", work_type=None, limit=10):
    records = await load_visible_records()
    all_members = get_top_members_dict(stat_doc)
    members_stats = [(uid, stats) for uid, stats in all_members.items()]

    if sort_by == "amount":
        sorted_list = sorted(members_stats, key=lambda x: x[1].get('total_amount', 0), reverse=True)
        title = f"🏆 أفضل {limit} أعضاء (إجمالي المبلغ)"
    elif sort_by == "chapters":
        sorted_list = sorted(members_stats, key=lambda x: x[1].get('total_entries', 0), reverse=True)
        title = f"📑 أفضل {limit} أعضاء (عدد الفصول)"
    elif sort_by == "by_type" and work_type:
        filtered = []
        for uid, stats in members_stats:
            uid_str = str(uid)
            if uid_str in records:
                count = sum(1 for e in records[uid_str] if e.get("work_type") == work_type)
                total = sum(e.get("total", 0) for e in records[uid_str] if e.get("work_type") == work_type)
                if count > 0:
                    filtered.append((uid, {"total_entries": count, "total_amount": total}))
        sorted_list = sorted(filtered, key=lambda x: x[1].get('total_amount', 0), reverse=True)
        title = f"🏆 أفضل {limit} أعضاء في {work_type.replace('_',' ').title()}"
    else:
        sorted_list = sorted(members_stats, key=lambda x: x[1].get('total_amount', 0), reverse=True)
        title = f"🏆 أفضل {limit} أعضاء"

    avatar = _bot_avatar()
    if not sorted_list:
        return cards.info_card(title, ["لا توجد بيانات كافية."], avatar_url=avatar)

    top_items = sorted_list[:limit]
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * (limit - 3)
    lines = []

    for i, (uid, stats_data) in enumerate(top_items, 1):
        uid_int = int(uid)
        member = guild.get_member(uid_int)  # محاولة من الكاش

        if member is None:
            try:
                member = await guild.fetch_member(uid_int)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None

        if member:
            display = member.mention
        else:
            uid_str = str(uid)
            fallback_name = None
            if uid_str in records:
                for e in records[uid_str]:
                    if e.get("username"):
                        fallback_name = e["username"]
                        break
            if not fallback_name:
                try:
                    user = await bot.fetch_user(uid_int)
                    fallback_name = user.display_name
                except:
                    fallback_name = f"مستخدم {uid_int}"
            display = f"**{fallback_name}** (غادر)"

        medal = medals[i-1] if i-1 < len(medals) else "🏅"
        if sort_by == "chapters":
            detail = f"{stats_data['total_entries']} فصل"
        else:
            detail = f"{currency}{stats_data['total_amount']:,.2f}"
        lines.append(f"{medal} **{i}.** {display}\n-# {detail}")

    footnote = None
    if len(top_items) < limit:
        footnote = f"يوجد فقط {len(top_items)} أعضاء في التصنيف الحالي • سيتم تحديث الإحصائية تلقائياً."

    children: list = [
        cards.header(["## " + title, f"**{len(top_items)}** أعضاء في التصنيف"], avatar),
        cards.sep(2),
        cards.text("\n\n".join(lines)),
    ]
    if footnote:
        children += [cards.sep(), cards.text(f"-# {footnote}")]
    children += [cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
    return cards.Card(cards.ACCENT_GOLD, *children)


# ═══════════════════════════════════════════════════════════════
# 📊 عارض الإحصائيات التفاعلي — أزرار الأقسام بنمط ZEUS
# ═══════════════════════════════════════════════════════════════
class StatsView(ui.LayoutView):
    def __init__(self, stat_doc, bot_member, currency, guild: discord.Guild):
        super().__init__(timeout=300.0)
        self.stat_doc = stat_doc
        self.bot_member = bot_member
        self.currency = currency if currency else '$'
        self.guild = guild
        self.current_page = "overview"
        self.rebuild()

    def accent(self):
        return cards.ACCENT_GOLD

    def rebuild(self):
        self.clear_items()
        children = self._build_children()
        children.append(cards.sep())
        children.append(cards.text(f"-# {cards.BOT_SIGNATURE}"))
        self.add_item(cards.container(self.accent(), *children))

    async def refresh(self, interaction: discord.Interaction):
        self.rebuild()
        await interaction.response.edit_message(view=self)

    def _tabs_row(self):
        active_style = discord.ButtonStyle.success
        idle_style = discord.ButtonStyle.secondary
        return cards.row(
            cards.make_button("🏠 الرئيسية", style=active_style if self.current_page == "overview" else idle_style,
                              callback=self._overview_callback),
            cards.make_button("📊 التخصصات", style=active_style if self.current_page == "types" else idle_style,
                              callback=self._types_callback),
            cards.make_button("⏳ زمني", style=active_style if self.current_page == "time" else idle_style,
                              callback=self._time_callback),
            cards.make_button("🏆 الأفضل", style=active_style if self.current_page == "top" else idle_style,
                              callback=self._enter_top_mode),
        )

    def _build_children(self) -> list:
        avatar = self.bot_member.display_avatar.url
        children: list = [
            cards.header(["## 📊 لوحة الإحصائيات", "مؤشرات الفريق الحية المحدثة تلقائيًا."], avatar),
            cards.sep(2),
        ]
        children += self._page_children()
        children += [cards.sep(), self._tabs_row()]
        return children

    def _page_children(self) -> list:
        if self.current_page == "types":
            return self._types_body()
        if self.current_page == "time":
            return self._time_body()
        if self.current_page == "top":
            return []
        return self._overview_body()

    def _overview_body(self):
        total_entries = self.stat_doc.get("total_entries", 0)
        total_amount = self.stat_doc.get("total_amount", 0)
        active = len(get_top_members_dict(self.stat_doc))
        return [
            cards.text(
                f"**📄 إجمالي الفصول:** {total_entries}\n"
                f"**💰 إجمالي المبالغ:** {self.currency}{total_amount:,.2f}\n"
                f"**👥 الأعضاء النشطون:** {active}"
            ),
        ]

    def _types_body(self):
        total_entries = self.stat_doc.get("total_entries", 0)
        type_counts = self.stat_doc.get("type_counts", {})
        if not type_counts:
            return [cards.text("لا توجد بيانات تخصصات بعد.")]
        lines = []
        for k, v in type_counts.items():
            pct = (v / total_entries * 100) if total_entries else 0
            bar = cards.progress_bar(v, total_entries or 1)
            lines.append(f"**{k.replace('_',' ').title()}** — {bar} **{pct:.0f}%** ({v})")
        return [cards.text("\n".join(lines)), cards.sep(), cards.text("-# شريط التقدم يمثل النسبة من إجمالي الفصول.")]

    def _time_body(self):
        daily = self.stat_doc.get("daily", {"entries": 0, "amount": 0})
        weekly = self.stat_doc.get("weekly", {"entries": 0, "amount": 0})
        monthly = self.stat_doc.get("monthly", {"entries": 0, "amount": 0})
        total_entries = self.stat_doc.get("total_entries", 0)
        total_amount = self.stat_doc.get("total_amount", 0)
        return [
            cards.text(
                f"**📅 اليوم** — 📑 {daily['entries']} فصل • 💰 {self.currency}{daily['amount']:,.2f}\n"
                f"**📆 الأسبوع** — 📑 {weekly['entries']} فصل • 💰 {self.currency}{weekly['amount']:,.2f}\n"
                f"**📅 الشهر** — 📑 {monthly['entries']} فصل • 💰 {self.currency}{monthly['amount']:,.2f}\n"
                f"**🌐 الإجمالي الكلي (منذ البداية)** — 📑 {total_entries} فصل • 💰 {self.currency}{total_amount:,.2f}"
            ),
            cards.sep(),
            cards.text("-# إحصائيات تراكمية لنفس اليوم / الأسبوع / الشهر."),
        ]

    # ── نظام «الأفضل» التفاعلي ──
    async def _overview_callback(self, interaction: discord.Interaction):
        self.current_page = "overview"
        await self.refresh(interaction)

    async def _types_callback(self, interaction: discord.Interaction):
        self.current_page = "types"
        await self.refresh(interaction)

    async def _time_callback(self, interaction: discord.Interaction):
        self.current_page = "time"
        await self.refresh(interaction)

    async def _enter_top_mode(self, interaction: discord.Interaction):
        top = await StatsTopView.create(self.stat_doc, self.guild, self.currency, stat_view=self)
        await interaction.response.edit_message(view=top)


class StatsTopView(ui.LayoutView):
    """عارض مستقل لقسم الأفضل داخل /احصائيات و /توب (قائمة تصنيف + عودة)."""

    def __init__(self, stat_doc, guild: discord.Guild, currency, stat_view: StatsView | None = None):
        super().__init__(timeout=300.0)
        self.stat_doc = stat_doc
        self.guild = guild
        self.currency = currency if currency else '$'
        self.stat_view = stat_view
        self.sort_by = "amount"
        self.current_type = None

    @classmethod
    async def create(cls, stat_doc, guild: discord.Guild, currency, stat_view: StatsView | None = None):
        self = cls(stat_doc, guild, currency, stat_view)
        await self.rebuild_async()
        return self

    async def rebuild_async(self):
        self.clear_items()
        children = await self._children()
        children.append(cards.sep())
        children.append(cards.text(f"-# {cards.BOT_SIGNATURE}"))
        self.add_item(cards.container(cards.ACCENT_GOLD, *children))

    async def refresh(self, interaction: discord.Interaction):
        await self.rebuild_async()
        await interaction.response.edit_message(view=self)

    async def _filter_selected(self, interaction: discord.Interaction):
        value = interaction.data['values'][0]
        if value == "by_type":
            self.sort_by = "by_type"
            self.current_type = None
        else:
            self.sort_by = value
            self.current_type = None
        await self.refresh(interaction)

    async def _type_selected(self, interaction: discord.Interaction):
        self.current_type = interaction.data['values'][0]
        self.sort_by = "by_type"
        await self.refresh(interaction)

    async def _back(self, interaction: discord.Interaction):
        if self.stat_view is not None:
            self.stat_view.current_page = "overview"
            await self.stat_view.refresh(interaction)
        else:
            self.sort_by = "amount"
            self.current_type = None
            await self.refresh(interaction)

    async def _children(self) -> list:
        avatar = _bot_avatar()
        children: list = [
            cards.header(["## 🏆 ترتيب الأعضاء", "اختر معيار التصنيف من القائمة."], avatar),
            cards.sep(2),
        ]
        if self.sort_by == "by_type" and self.current_type is None:
            type_counts = self.stat_doc.get("type_counts", {})
            if not type_counts:
                children.append(cards.text("لا توجد بيانات تخصصات."))
            else:
                options = [discord.SelectOption(label=cards.clamp(k.replace('_',' ').title(), 100), value=k, emoji="📊")
                           for k in list(type_counts.keys())[:25]]
                children.append(cards.text("-# اختر التخصص لعرض أفضل الأعضاء فيه."))
                children.append(cards.sep())
                children.append(cards.make_select("اختر التخصص...", options, self._type_selected))
        else:
            card_built = await build_top_card(self.guild, self.currency, self.stat_doc,
                                              self.sort_by, self.current_type)
            # استخراج محتوى البطاقة المبنية وإعادة استخدام عناصرها النصية
            container = card_built.children[0]
            for child in container.children:
                if isinstance(child, (ui.TextDisplay, ui.Section, ui.Separator, ui.ActionRow)):
                    children.append(child)

        options = [
            discord.SelectOption(label="الأفضل عاماً (إجمالي المبلغ)", value="amount", emoji="💰"),
            discord.SelectOption(label="الأفضل في الفصول (العدد)", value="chapters", emoji="📑"),
            discord.SelectOption(label="الأفضل في تخصص...", value="by_type", emoji="📊"),
        ]
        children.append(cards.sep())
        children.append(cards.make_select("اختر معيار التصنيف...", options, self._filter_selected))
        children.append(cards.sep())
        children.append(cards.row(cards.secondary_btn("عودة", self._back, emoji="↩")))
        return children


# ═══════════════════════════════════════════════════════════════
# 1️⃣ أمر الأعمال
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="الأعمال", description="عرض جميع الأعمال والاعضاء")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def projects_report(interaction: discord.Interaction):
    if interaction.channel.name not in SETTINGS.get("allowed_channels", []):
        await interaction.response.send_message(
            view=cards.channel_card(SETTINGS.get("allowed_channels", []), _bot_avatar()), ephemeral=True)
        return

    works_info = await get_works_info(interaction.guild)
    if not works_info:
        await interaction.response.send_message(view=cards.info_card(
            "📭 لا توجد أعمال", ["لا توجد أعمال مسجلة في القائمة."], avatar_url=_bot_avatar()), ephemeral=True)
        return

    view = WorksPaginator(works_info, interaction.guild)
    await interaction.response.send_message(view=view)


# ═══════════════════════════════════════════════════════════════
# 2️⃣ إحصائيات (نظام تفاعلي كامل)
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="احصائيات", description="عرض إحصائيات متقدمة")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def stats(interaction: discord.Interaction):
    stat_doc = await stats_collection.find_one({"_id": "stats"})
    if not stat_doc:
        await interaction.response.send_message(view=cards.info_card(
            "📭 لا توجد إحصائيات", ["لا توجد إحصائيات بعد."], avatar_url=_bot_avatar()), ephemeral=True)
        return

    bot_member = interaction.guild.me
    currency = SETTINGS.get('currency', '$') or '$'
    view = StatsView(stat_doc, bot_member, currency, interaction.guild)
    await interaction.response.send_message(view=view)


# ═══════════════════════════════════════════════════════════════
# 2.5️⃣ /توب (ترتيب الأعضاء المستقل)
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="توب", description="عرض ترتيب الأعضاء حسب معايير مختلفة")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def top_members(interaction: discord.Interaction):
    stat_doc = await stats_collection.find_one({"_id": "stats"})
    if not stat_doc:
        await interaction.response.send_message(view=cards.info_card(
            "📭 لا توجد بيانات", ["لا توجد بيانات إحصائية بعد."], avatar_url=_bot_avatar()), ephemeral=True)
        return

    currency = SETTINGS.get('currency', '$') or '$'
    view = StatsTopView(stat_doc, interaction.guild, currency, stat_view=None)
    await interaction.response.send_message(view=view)


# ═══════════════════════════════════════════════════════════════
# 2.7️⃣ /الأعضاء + /اعضاء_تخصص
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="الأعضاء", description="عرض جميع الأعضاء المسجلين مع أموالهم وسجلاتهم")
@app_commands.describe(بحث="بحث اختياري باسم العضو أو معرفه")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def registered_members(interaction: discord.Interaction, بحث: str = None):
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "الأعضاء")
        await interaction.response.send_message(view=cards.permission_card(_bot_avatar()), ephemeral=True)
        return

    records = await load_visible_records()
    rows = _build_member_finance_rows(records, interaction.guild, بحث)
    if not rows:
        await interaction.response.send_message(view=cards.info_card(
            "📭 لا توجد نتائج", ["لا توجد نتائج مطابقة للأعضاء المسجلين."], avatar_url=_bot_avatar()), ephemeral=True)
        return
    title = "👥 الأعضاء المسجلون والمستحقات"
    if بحث:
        title += f" • بحث: {بحث}"
    view = MembersFinancePaginator(rows, interaction.guild, SETTINGS.get('currency', '$'), title)
    await interaction.response.send_message(view=view)


@bot.tree.command(name="اعضاء_تخصص", description="عرض أعضاء تخصص معين مع مستحقاتهم وأعمالهم")
@app_commands.autocomplete(التخصص=specialty_autocomplete)
@app_commands.describe(التخصص="التخصص المطلوب عرضه")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def specialty_members(interaction: discord.Interaction, التخصص: str):
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "اعضاء_تخصص")
        await interaction.response.send_message(view=cards.permission_card(_bot_avatar()), ephemeral=True)
        return

    specialty = map_type(التخصص)
    records = await load_visible_records()
    filtered_records = {}
    for user_id, entries in records.items():
        matched = [entry for entry in entries if entry.get("work_type") == specialty]
        if matched:
            filtered_records[user_id] = matched
    rows = _build_member_finance_rows(filtered_records, interaction.guild)
    rows.sort(key=lambda row: (row["chapters"], row["net_total"]), reverse=True)
    if not rows:
        await interaction.response.send_message(view=cards.info_card(
            "📭 لا يوجد أعضاء", [f"لا يوجد أعضاء مسجلون في تخصص `{specialty}`."], avatar_url=_bot_avatar()), ephemeral=True)
        return
    view = SpecialtyMembersPaginator(rows, interaction.guild, SETTINGS.get('currency', '$'), specialty)
    await interaction.response.send_message(view=view)


# ═══════════════════════════════════════════════════════════════
# 3️⃣ أعمالي
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="أعمالي", description="عرض أعمالك مجمعة مع المكافآت والخصومات")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def my_works_slash(interaction: discord.Interaction):
    if interaction.channel.name not in SETTINGS.get("allowed_channels", []):
        await interaction.response.send_message(
            view=cards.channel_card(SETTINGS.get("allowed_channels", []), _bot_avatar()), ephemeral=True)
        return

    records = await load_visible_records()
    user_id = str(interaction.user.id)
    if user_id not in records or not records[user_id]:
        await interaction.response.send_message(view=cards.info_card(
            "📭 ليس لديك أي شغل", ["لم تسجل أي فصول بعد — ابدأ بأمر /تسجيل."], avatar_url=_bot_avatar()), ephemeral=True)
        return

    works, bonuses, deductions = _categorize_records(records[user_id])
    view = WorkSummarySelectView(
        works, bonuses, deductions,
        member=interaction.user,
        user_id=user_id,
        currency=SETTINGS.get('currency', '$'),
        title_prefix="💼 اللوحة الشخصية •"
    )
    await interaction.response.send_message(view=view)


@bot.command(name="أعمالي")
@commands.cooldown(1, 5, commands.BucketType.user)
async def my_works_text(ctx):
    records = await load_visible_records()
    user_id = str(ctx.author.id)
    if user_id not in records or not records[user_id]:
        await ctx.send("📭 ليس لديك أي شغل.")
        return

    works, bonuses, deductions = _categorize_records(records[user_id])
    view = WorkSummarySelectView(
        works, bonuses, deductions,
        member=ctx.author,
        user_id=user_id,
        currency=SETTINGS.get('currency', '$'),
        title_prefix="💼 اللوحة الشخصية •"
    )
    await ctx.send(view=view)


# ═══════════════════════════════════════════════════════════════
# 4️⃣ شغل
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="شغل", description="عرض شغل عضو مجمّع مع المكافآت والخصومات")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def show_work_slash(interaction: discord.Interaction, member: discord.Member = None):
    if interaction.channel.name not in SETTINGS.get("allowed_channels", []):
        await interaction.response.send_message(
            view=cards.channel_card(SETTINGS.get("allowed_channels", []), _bot_avatar()), ephemeral=True)
        return

    target = member or interaction.user
    records = await load_visible_records()
    user_id = str(target.id)
    if user_id not in records or not records[user_id]:
        await interaction.response.send_message(view=cards.info_card(
            "📭 لا يوجد شغل", [f"لا يوجد شغل للعضو {target.mention}."], avatar_url=_bot_avatar()), ephemeral=True)
        return

    works, bonuses, deductions = _categorize_records(records[user_id])
    view = WorkSummarySelectView(
        works, bonuses, deductions,
        member=target,
        user_id=user_id,
        currency=SETTINGS.get('currency', '$'),
        title_prefix="📊 ملخص شغل"
    )
    await interaction.response.send_message(view=view)


@bot.command(name="شغل")
@commands.cooldown(1, 5, commands.BucketType.user)
async def show_work_text(ctx, member: discord.Member = None):
    member = member or ctx.author
    records = await load_visible_records()
    user_id = str(member.id)
    if user_id not in records or not records[user_id]:
        await ctx.send(f"📭 ما عندي أي شغل للعضو {member.mention}.")
        return

    works, bonuses, deductions = _categorize_records(records[user_id])
    view = WorkSummarySelectView(
        works, bonuses, deductions,
        member=member,
        user_id=user_id,
        currency=SETTINGS.get('currency', '$'),
        title_prefix="📊 ملخص شغل"
    )
    await ctx.send(view=view)


def _categorize_records(entries):
    works = {}
    bonuses = []
    deductions = []
    for entry in entries:
        wtype = entry.get("work_type")
        if wtype == "مكافأة":
            bonuses.append(entry)
        elif wtype == "خصم":
            deductions.append(entry)
        else:
            work = entry.get("work_name", "غير محدد")
            works.setdefault(work, []).append(entry)
    return works, bonuses, deductions


def _member_name_from_entries(entries):
    for entry in entries:
        if entry.get("username"):
            return entry.get("username")
    return None


def _build_member_finance_rows(records, guild, search: str = None):
    rows = []
    search_text = search.lower().strip() if search else None
    for user_id, entries in records.items():
        works, bonuses, deductions = _categorize_records(entries)
        work_entries = [entry for work_entries in works.values() for entry in work_entries]
        total_works = sum(entry.get("total", 0) for entry in work_entries)
        total_bonus = sum(entry.get("total", 0) for entry in bonuses)
        total_deduct = sum(abs(entry.get("total", 0)) for entry in deductions)
        net_total = total_works + total_bonus - total_deduct
        username_hint = _member_name_from_entries(entries)
        display = format_member_display(guild, int(user_id), username_hint)
        mention = f"<@{user_id}>"
        if search_text and search_text not in display.lower() and search_text not in user_id:
            continue
        work_counts = sorted(
            ((work_name, len(work_entries), sum(e.get("total", 0) for e in work_entries)) for work_name, work_entries in works.items()),
            key=lambda item: (item[1], item[2]),
            reverse=True
        )
        type_counts = defaultdict(int)
        for entry in work_entries:
            type_counts[entry.get("work_type", "غير محدد")] += 1
        rows.append({
            "user_id": user_id,
            "display": display,
            "mention": mention,
            "records": len(entries),
            "chapters": len(work_entries),
            "works_count": len(works),
            "total_works": total_works,
            "bonuses": total_bonus,
            "deductions": total_deduct,
            "net_total": net_total,
            "work_counts": work_counts,
            "type_counts": dict(type_counts),
        })
    return sorted(rows, key=lambda row: (row["net_total"], row["chapters"]), reverse=True)


# ═══════════════════════════════════════════════════════════════
# 📄 مُصفّحات الأعضاء — بطاقات بتنقل ZEUS
# ═══════════════════════════════════════════════════════════════
class MembersFinancePaginator(ui.LayoutView):
    def __init__(self, rows, guild, currency, title="👥 الأعضاء والمستحقات", per_page=6):
        super().__init__(timeout=300.0)
        self.rows = rows
        self.guild = guild
        self.currency = currency or '$'
        self.title = title
        self.per_page = per_page
        self.current_page = 0
        self.total_pages = max(1, (len(rows) + per_page - 1) // per_page)
        self.rebuild()

    def accent(self):
        return cards.ACCENT_GOLD

    def _row_block(self, index, row) -> str:
        works_preview = "، ".join(f"{name} ({count})" for name, count, _total in row["work_counts"][:3]) or "لا توجد أعمال"
        if len(row["work_counts"]) > 3:
            works_preview += f"، +{len(row['work_counts']) - 3}"
        return (
            f"**{index}. {row['display']}**\n"
            f"{row['mention']}\n"
            f"-# 📑 الفصول: **{row['chapters']}** | السجلات: **{row['records']}** | الأعمال: **{row['works_count']}**\n"
            f"-# 💰 الأعمال: {self.currency}{row['total_works']:.2f} | 🎁 مكافآت: {self.currency}{row['bonuses']:.2f} | 🔻 خصومات: {self.currency}{row['deductions']:.2f}\n"
            f"-# 💵 الصافي: **{self.currency}{row['net_total']:.2f}**\n"
            f"-# 📚 أبرز الأعمال: {works_preview}"
        )

    def _summary_line(self) -> str:
        total_amount = sum(row["net_total"] for row in self.rows)
        total_chapters = sum(row["chapters"] for row in self.rows)
        return (f"**عدد الأعضاء:** {len(self.rows)} • **الفصول المحتسبة:** {total_chapters}"
                f" • **الصافي:** {self.currency}{total_amount:.2f}")

    def _footnote(self) -> str | None:
        return "الأعمال المعزولة مستبعدة من هذه الأرقام تلقائياً."

    def _body(self) -> list:
        start = self.current_page * self.per_page
        page_rows = self.rows[start:start + self.per_page]
        blocks = [self._row_block(index, row) for index, row in enumerate(page_rows, start + 1)]
        return [cards.text(cards.clamp("\n\n".join(blocks), 3400))]

    def rebuild(self):
        self.clear_items()
        avatar = _bot_avatar()
        children: list = [
            cards.header([f"## {self.title}", self._summary_line()], avatar),
            cards.sep(2),
        ]
        children += self._body()
        footnote = self._footnote()
        if footnote:
            children += [cards.sep(), cards.text(f"-# {footnote}")]
        if self.total_pages > 1:
            children += [cards.sep(), cards.pager_row(self.current_page, self.total_pages,
                                                      self.previous_page, self.next_page)]
        children += [cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
        self.add_item(cards.container(self.accent(), *children))

    async def refresh(self, interaction: discord.Interaction):
        self.rebuild()
        await interaction.response.edit_message(view=self)

    async def previous_page(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        await self.refresh(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        await self.refresh(interaction)


class SpecialtyMembersPaginator(MembersFinancePaginator):
    def __init__(self, rows, guild, currency, specialty, per_page=7):
        self.specialty = specialty
        super().__init__(rows, guild, currency, f"🛠️ أعضاء تخصص: {specialty}", per_page)

    def accent(self):
        return cards.ACCENT_GOLD

    def _row_block(self, index, row) -> str:
        works_preview = "، ".join(f"{name} ({count})" for name, count, _total in row["work_counts"][:4]) or "لا توجد أعمال"
        return (
            f"**{index}. {row['display']}**\n"
            f"{row['mention']}\n"
            f"-# 📑 فصول التخصص: **{row['chapters']}** | 📚 الأعمال: **{row['works_count']}**\n"
            f"-# 💵 المستحق: **{self.currency}{row['net_total']:.2f}**\n"
            f"-# 📖 الأعمال: {works_preview}"
        )

    def _summary_line(self) -> str:
        total_amount = sum(row["net_total"] for row in self.rows)
        total_chapters = sum(row["chapters"] for row in self.rows)
        return (f"**عدد الأعضاء:** {len(self.rows)} • **الفصول:** {total_chapters}"
                f" • **الإجمالي:** {self.currency}{total_amount:.2f}")

    def _footnote(self) -> str | None:
        return "مرتّب من الأكثر فصولاً إلى الأقل • الأعمال المعزولة مستبعدة."


# ═══════════════════════════════════════════════════════════════
# 5️⃣ لوحة التحكم
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="لوحة_التحكم", description="لوحة تحكم للمشرفين")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def dashboard(interaction: discord.Interaction):
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "لوحة_التحكم")
        await interaction.response.send_message(view=cards.permission_card(_bot_avatar()), ephemeral=True)
        return

    avatar = _bot_avatar()
    records = await load_visible_records()
    total_users = len(records)
    total_entries = sum(len(entries) for entries in records.values())
    total_amount = sum(sum(e.get("total", 0) for e in entries) for entries in records.values())
    currency = SETTINGS.get('currency', '$') or '$'
    member_rows = _build_member_finance_rows(records, interaction.guild)
    top_members_preview = "\n".join(
        f"• {row['mention']} — {row['chapters']} فصول — {currency}{row['net_total']:.2f}"
        for row in member_rows[:5]
    ) or "لا توجد بيانات أعضاء."
    isolated_count = len(get_isolated_work_names(await load_works()))
    notify_channel = SETTINGS.get('notify_channel_id')
    backup_channel = SETTINGS.get('daily_backup_channel_id')
    payment_day = SETTINGS.get("payment_day")

    children: list = [
        cards.header(["## 🖥️ لوحة التحكم الرئيسية",
                      f"<@{interaction.user.id}> — مركز إدارة شامل للمشرفين."], avatar),
        cards.sep(2),
        cards.text(
            f"**👥 الأعضاء النشطون:** {total_users}\n"
            f"**📄 عدد السجلات الكلي:** {total_entries}\n"
            f"**💰 إجمالي المبالغ:** {currency}{total_amount:.2f}"
        ),
        cards.sep(),
        cards.text(
            f"**⚙️ العملة:** {currency}\n"
            f"**🔔 قناة الإشعارات:** {('<#' + str(notify_channel) + '>') if notify_channel else 'غير محدد'}\n"
            f"**💾 قناة النسخ الاحتياطي:** {('<#' + str(backup_channel) + '>') if backup_channel else 'غير محدد'}\n"
            f"**⚠️ حد التنبيه:** {currency}{SETTINGS.get('alert_threshold', 10):.2f}\n"
            f"**📅 موعد الدفع الشهري:** " +
            (f"يوم {payment_day} الساعة {SETTINGS.get('payment_hour', 0)}:00" if payment_day else "غير محدد")
        ),
        cards.sep(),
        cards.text(f"**👥 أعلى الأعضاء حالياً**\n{top_members_preview}"),
        cards.sep(),
        cards.text(
            "**⏸️ الأعمال المعزولة**\n" +
            (f"{isolated_count} عمل مستبعد من الحسابات الظاهرة." if isolated_count else "لا يوجد أعمال معزولة.")
        ),
        cards.sep(),
        cards.row(
            cards.make_button("👥 قائمة الأعضاء", style=discord.ButtonStyle.secondary, callback=_quick_members),
            cards.make_button("💳 تقرير الدفع", style=discord.ButtonStyle.success, callback=_quick_payment),
            cards.make_button("🛠️ أعضاء تخصص", style=discord.ButtonStyle.secondary, callback=_quick_specialty),
        ),
        cards.sep(),
        cards.text(f"-# {cards.BOT_SIGNATURE}"),
    ]
    await interaction.response.send_message(view=cards.Card(cards.ACCENT_GOLD, *children))


async def _quick_members(interaction: discord.Interaction):
    await interaction.response.send_message(
        "استخدم الأمر `/الأعضاء` لعرض كل الأعضاء والمستحقات مع الصفحات والبحث.", ephemeral=True)


async def _quick_payment(interaction: discord.Interaction):
    await interaction.response.send_message(
        "استخدم الأمر `/تقرير_دفع` لمراجعة تقرير الدفع الشهري وتصديره.", ephemeral=True)


async def _quick_specialty(interaction: discord.Interaction):
    await interaction.response.send_message(
        "استخدم الأمر `/اعضاء_تخصص` ثم اختر التخصص المطلوب لمراجعة أعضائه قبل الصرف.", ephemeral=True)


# ═══════════════════════════════════════════════════════════════
# 6️⃣ سجل العمليات
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="سجل", description="عرض آخر 20 عملية إدارية")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def audit_log(interaction: discord.Interaction):
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "سجل")
        await interaction.response.send_message(view=cards.permission_card(_bot_avatar()), ephemeral=True)
        return

    logs = await audit_collection.find().sort("timestamp", -1).limit(20).to_list(length=20)
    if not logs:
        await interaction.response.send_message(view=cards.info_card(
            "📜 سجل العمليات", ["لا توجد سجلات بعد."], avatar_url=_bot_avatar()), ephemeral=True)
        return

    bullets = []
    for log in logs:
        bullets.append(
            f"• **{log.get('action', 'غير معروف')}**\n"
            f"-# بواسطة: <@{log.get('moderator_id')}> • للـ: {log.get('target_id') if log.get('target_id') else 'عام'}\n"
            f"-# {cards.clamp(str(log.get('details')), 120)}\n"
            f"-# {str(log.get('timestamp'))[:19]}"
        )
    children: list = [
        cards.header(["## 📜 سجل العمليات", f"**{len(logs)}** عملية أحدث أولًا."], _bot_avatar()),
        cards.sep(2),
        cards.text(cards.clamp("\n\n".join(bullets), 3400)),
        cards.sep(),
        cards.text(f"-# {cards.BOT_SIGNATURE}"),
    ]
    await interaction.response.send_message(view=cards.Card(cards.ACCENT_GOLD, *children))


# ═══════════════════════════════════════════════════════════════
# 7️⃣ تقرير أسبوعي شخصي
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="تقريري", description="تقرير أسبوعي خاص بك")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def my_weekly_report(interaction: discord.Interaction):
    records = await load_visible_records()
    user_id = str(interaction.user.id)
    if user_id not in records:
        await interaction.response.send_message(view=cards.info_card(
            "📭 لا توجد سجلات", ["ليس لديك أي سجلات."], avatar_url=_bot_avatar()), ephemeral=True)
        return

    week_ago = datetime.utcnow() - timedelta(days=7)
    week_entries = [
        e for e in records[user_id]
        if "timestamp" in e and datetime.fromisoformat(e["timestamp"]) > week_ago
    ]
    if not week_entries:
        await interaction.response.send_message(view=cards.info_card(
            "📭 لا يوجد نشاط", ["لا يوجد فصول خلال الأسبوع الماضي."], avatar_url=_bot_avatar()), ephemeral=True)
        return

    total = sum(e.get("total", 0) for e in week_entries)
    currency = SETTINGS.get('currency', '$') or '$'
    children: list = [
        cards.header(["## 📅 تقريرك الأسبوعي", f"<@{interaction.user.id}>"], _bot_avatar()),
        cards.sep(2),
        cards.text(
            f"**عدد المهام:** {len(week_entries)}\n"
            f"**المجموع:** {currency}{total:.2f}"
        ),
        cards.sep(),
        cards.text(f"-# آخر 7 أيام • {cards.BOT_SIGNATURE}"),
    ]
    await interaction.response.send_message(view=cards.Card(cards.ACCENT_GREEN, *children))


# ═══════════════════════════════════════════════════════════════
# 8️⃣ تعديل آخر سجل
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="تعديل", description="تعديل آخر سجل قمت بإضافته")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def edit_last(interaction: discord.Interaction,
                    العمل: str = None,
                    الفصل: str = None,
                    التخصص: str = None,
                    ملاحظات: str = None):
    avatar = _bot_avatar()
    records = await load_records()
    user_id = str(interaction.user.id)
    if user_id not in records or not records[user_id]:
        await interaction.response.send_message(view=cards.info_card(
            "📭 لا توجد سجلات", ["لا يوجد سجلات."], avatar_url=avatar), ephemeral=True)
        return

    last = records[user_id][-1]
    changed = []
    if العمل:
        last["work_name"] = العمل
        changed.append(f"العمل ← {العمل}")
    if الفصل:
        last["chapter"] = الفصل
        changed.append(f"الفصل ← {الفصل}")
    if التخصص:
        norm_type = map_type(التخصص)
        if norm_type not in PRICES:
            await interaction.response.send_message(view=cards.error_card(
                "❌ التخصص غير صحيح", [f"التخصص `{التخصص}` غير موجود في القائمة."], avatar_url=avatar), ephemeral=True)
            return
        last["work_type"] = norm_type
        last["total"] = PRICES[norm_type]
        changed.append(f"التخصص ← {norm_type}")
    if ملاحظات is not None:
        last["notes"] = ملاحظات
        changed.append("الملاحظات ← محدثة")

    await save_records(records)
    await update_stats()
    detail = "\n".join(f"✓ {c}" for c in changed) or "لم تحدد أي تغيير."
    await interaction.response.send_message(view=cards.success_card(
        "✅ تم تعديل آخر سجل",
        [f"<@{interaction.user.id}>", detail],
        avatar_url=avatar), ephemeral=True)
