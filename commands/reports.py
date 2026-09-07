from datetime import datetime, timedelta, timezone
from collections import defaultdict
import discord
from discord import app_commands
from discord.ext import commands
from discord import ui
from state import bot
from helpers.core import *
from views.paginators import WorksPaginator, get_works_info
from tasks.lifecycle import specialty_autocomplete
from ui import cards
from commands.admin import PaymentReportPaginator, build_payment_rows


def _bot_avatar():
    return bot.user.display_avatar.url if bot.user else None


def _member_avatar(member):
    try:
        return member.display_avatar.url if member else None
    except Exception:
        return None


def _medal(rank: int) -> str:
    """التاج للمركز الأول فقط — بلا ميداليات ملونة."""
    return cards.rank_prefix(rank)


# ═══════════════════════════════════════════════════════════════
# 🔙 نظام العودة الموحد: back يكون view جاهزًا أو دالة (متزامنة أو
#   غير متزامنة) تُعيد العرض الأب — بحيث تُبنى لوحة التحكم ببيانات
#   حية عند كل عودة إليها.
# ═══════════════════════════════════════════════════════════════
class BackNav:
    back = None

    async def _resolve_back(self):
        if self.back is None:
            return None
        if callable(self.back):
            result = self.back()
            if hasattr(result, "__await__"):
                result = await result
            return result
        return self.back

    async def _back_cb(self, interaction: discord.Interaction):
        parent = await self._resolve_back()
        if parent is None:
            await interaction.response.defer()
            return
        await interaction.response.edit_message(view=parent)

    def _back_row(self, label="عودة") -> ui.ActionRow:
        return cards.row(cards.secondary_btn(label, self._back_cb, emoji="↩"))


# ═══════════════════════════════════════════════════════════════
# 🎨 ملخص شغل عضو — بطاقة حية بقائمة أعمال منسدلة + تفاصيل
#   الصورة المصغرة دائمًا لصورة العضو المعنيّ وليس صورة البوت.
# ═══════════════════════════════════════════════════════════════
class WorkSummarySelectView(ui.LayoutView):
    def __init__(self, works, bonuses, deductions, member, user_id,
                 currency, title_prefix="ملخص شغل"):
        super().__init__(timeout=600.0)
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
        # كل رقم في سطر مستقل — قراءة مريحة بلا حشو
        lines = [
            "### الحصيلة الكلية",
            f"**الأعمال:** {total_works}",
            f"**الفصول:** {total_chapters}",
            f"**💰 قيمة الأعمال:** {self.currency}{gross:,.2f}",
        ]
        if total_bonus:
            lines.append(f"**المكافآت:** {self.currency}{total_bonus:,.2f}")
        if total_deduct:
            lines.append(f"**الخصومات:** {self.currency}{total_deduct:,.2f}")
        lines.append(f"**💰 الصافي النهائي:** {self.currency}{net:,.2f}")
        return lines

    def _summary_children(self, avatar):
        children: list = [
            cards.header([f"## {self.title_prefix}",
                          f"{self.member.mention}"], avatar),
            cards.sep(2),
            cards.text("\n".join(self._summary_stats_lines())),
        ]
        # ترتيب الأعمال من الأكثر فصولًا
        ranked = sorted(self.works.items(), key=lambda kv: len(kv[1]), reverse=True)
        options = []
        for i, (work_name, entries) in enumerate(ranked):
            if i >= 24:
                break
            chapters = len(entries)
            total = sum(e.get("total", 0) for e in entries)
            options.append(discord.SelectOption(
                label=cards.clamp(work_name, 100), value=work_name,
                description=cards.clamp(f"{chapters} فصول • {self.currency}{total:,.2f}", 100), emoji="📖"))
        if self.bonuses or self.deductions:
            options.append(discord.SelectOption(label="المكافآت والخصومات", value="__bonuses__",
                                                description="تفاصيل المكافآت والخصومات", emoji="⚖️"))
        if len(self.works) > 1:
            options.append(discord.SelectOption(label="عرض كل الفصول", value="__all__",
                                                description="جميع الفصول مجمعة", emoji="📚"))
        if options:
            children += [cards.sep(),
                         cards.text("-# اختر عملاً من القائمة لعرض تفاصيله الدقيقة."),
                         cards.make_select("اختر عملاً لعرض التفاصيل...", options, self.select_callback)]
        return children

    def _work_children(self, work_name, avatar):
        entries = sort_entries_by_chapter(self.works[work_name])
        total = sum(e.get("total", 0) for e in entries)
        count = len(entries)
        avg = (total / count) if count else 0
        types_count = {}
        for e in entries:
            t = e.get("work_type", "غير محدد")
            c, a = types_count.get(t, (0, 0.0))
            types_count[t] = (c + 1, a + e.get("total", 0))
        max_c = max(c for c, _ in types_count.values())
        type_lines = [f"• **{t.replace('_', ' ').title()}** — {cards.progress_bar(c, max_c)} **{c}** فصول — {self.currency}{a:,.2f}"
                      for t, (c, a) in sorted(types_count.items(), key=lambda kv: -kv[1][0])]

        ch_lines = []
        for e in entries:
            note = f"\n  -# {e.get('notes')}" if e.get("notes") else ""
            ch_lines.append(f"• **فصل {e.get('chapter', '؟')}** — {e.get('work_type', 'غير محدد')} — {self.currency}{e.get('total', 0):.2f}{note}")
        shown = "\n".join(ch_lines[:12])
        if len(ch_lines) > 12:
            shown += f"\n-# … و{len(ch_lines) - 12} فصلًا إضافيًا"

        body = "\n".join([
            "### الملخص",
            f"**الفصول:** {count}",
            f"**💰 المجموع:** {self.currency}{total:,.2f}",
            f"**متوسط الفصل:** {self.currency}{avg:,.2f}",
            "",
            "### التوزيع على التخصصات",
            *type_lines,
            "",
            "### الفصول (مرتبة رقميًا)",
            shown,
        ])
        children: list = [
            cards.header([f"## {cards.clamp(work_name, 60)}",
                          f"{self.member.mention}"], avatar),
            cards.sep(2),
            cards.text(cards.clamp(body, 3600)),
            cards.sep(),
            self._back_row(),
        ]
        return children

    def _all_children(self, avatar):
        children: list = [
            cards.header(["## جميع الفصول",
                          f"{self.member.mention}"], avatar),
            cards.sep(2),
        ]
        chunks = []
        for work_name, entries in sorted(self.works.items(), key=lambda kv: -len(kv[1])):
            total = sum(e.get("total", 0) for e in entries)
            cnt = len(entries)
            preview = [f"  • فصل {e.get('chapter','؟')} — {e.get('work_type','؟')} — {self.currency}{e.get('total',0):.2f}"
                       for e in sort_entries_by_chapter(entries)[:4]]
            if len(entries) > 4:
                preview.append("  -# … والمزيد")
            chunks.append(f"**{work_name}** ({cnt} فصل — {self.currency}{total:,.2f})\n" + "\n".join(preview))
        children.append(cards.text(cards.clamp("\n\n".join(chunks), 3400)))
        children += [cards.sep(), self._back_row()]
        return children

    def _bonuses_children(self, avatar):
        children: list = [
            cards.header(["## المكافآت والخصومات",
                          f"{self.member.mention}"], avatar),
            cards.sep(2),
        ]
        bon_lines = [f"• فصل {e.get('chapter','مكافأة')}: **{self.currency}{e.get('total',0):,.2f}** — {e.get('notes','')}"
                     for e in self.bonuses] or ["• لا يوجد"]
        ded_lines = [f"• فصل {e.get('chapter','خصم')}: **{self.currency}{abs(e.get('total',0)):,.2f}** — {e.get('notes','')}"
                     for e in self.deductions] or ["• لا يوجد"]
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


# ═══════════════════════════════════════════════════════════════
# 🏆 /توب — عارض الترتيب (نسخة مُصلحة بالكامل)
#   ملاحظة حرجة: لا يُسمح بتسمية أي دالة أو خاصية `_children`
#   لأن discord.py يستخدم هذا الاسم داخليًا (كان سبب تعطل /توب).
# ═══════════════════════════════════════════════════════════════
class TopView(BackNav, ui.LayoutView):
    def __init__(self, stat_doc, guild: discord.Guild, currency, back=None):
        super().__init__(timeout=600.0)
        self.stat_doc = stat_doc or {}
        self.guild = guild
        self.currency = currency if currency else '$'
        self.back = back
        self.sort_by = "amount"
        self.current_type = None
        self._member_cache = {}

    @classmethod
    async def create(cls, stat_doc, guild: discord.Guild, currency, back=None):
        self = cls(stat_doc, guild, currency, back)
        await self.rebuild_async()
        return self

    async def rebuild_async(self):
        self.clear_items()
        children = await self.build_children()
        children.append(cards.sep())
        children.append(cards.text(f"-# {cards.BOT_SIGNATURE}"))
        self.add_item(cards.container(cards.ACCENT_GOLD, *children))

    async def refresh(self, interaction: discord.Interaction):
        await self.rebuild_async()
        await interaction.response.edit_message(view=self)

    async def _resolve_member(self, uid_int: int):
        if uid_int in self._member_cache:
            return self._member_cache[uid_int]
        member = self.guild.get_member(uid_int) if self.guild else None
        if member is None and self.guild:
            try:
                member = await self.guild.fetch_member(uid_int)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None
        self._member_cache[uid_int] = member
        return member

    async def _ranking_lines(self) -> tuple[str, list]:
        records = await load_visible_records()
        members_stats = list(get_top_members_dict(self.stat_doc).items())
        by_type = self.sort_by == "by_type" and self.current_type

        if by_type:
            filtered = []
            for uid, _stats in members_stats:
                entries = [e for e in records.get(str(uid), [])
                           if e.get("work_type") == self.current_type]
                if entries:
                    filtered.append((uid, {
                        "total_entries": len(entries),
                        "total_amount": sum(e.get("total", 0) for e in entries),
                    }))
            sorted_list = sorted(filtered, key=lambda x: x[1]["total_amount"], reverse=True)
            title = f"أبطال تخصص **{str(self.current_type).replace('_', ' ').title()}**"
        elif self.sort_by == "chapters":
            sorted_list = sorted(members_stats, key=lambda x: x[1].get("total_entries", 0), reverse=True)
            title = "الترتيب حسب **عدد الفصول**"
        else:
            sorted_list = sorted(members_stats, key=lambda x: x[1].get("total_amount", 0), reverse=True)
            title = "الترتيب حسب **إجمالي المبلغ**"

        lines = []
        for i, (uid, stats) in enumerate(sorted_list[:10], 1):
            member = await self._resolve_member(int(uid))
            if member:
                display = member.mention
            else:
                display = f"<@{uid}> (غادر)"
            lines.append(
                f"{cards.rank_prefix(i)} {display}\n"
                f"-# 💰 {self.currency}{stats.get('total_amount', 0):,.2f} • {stats.get('total_entries', 0)} فصل"
            )
        if not lines:
            lines = ["*لا توجد بيانات كافية في هذا التصنيف بعد.*"]
        return title, lines

    async def build_children(self) -> list:
        avatar = _bot_avatar()
        month_label = await get_month_name(get_active_month_key())
        if self.sort_by == "by_type" and self.current_type is None:
            subtitle = f"اختر التخصص ثم معيار الترتيب — لشهر **{month_label}**."
            children: list = [
                cards.header(["## ترتيب الأعضاء", subtitle], avatar),
                cards.sep(2),
            ]
            type_counts = self.stat_doc.get("type_counts", {})
            if not type_counts:
                children.append(cards.text("لا توجد تخصصات مسجلة بعد — الأرقام تظهر مع أول تسجيل."))
            else:
                options = [discord.SelectOption(label=cards.clamp(k.replace('_', ' ').title(), 100), value=k, emoji="📊")
                           for k in list(type_counts.keys())[:25]]
                children.append(cards.text("-# **الخطوة 1 من 2** — اختر التخصص لعرض أبطاله."))
                children.append(cards.sep())
                children.append(cards.make_select("اختر التخصص...", options, self._type_selected))
        else:
            title, lines = await self._ranking_lines()
            children: list = [
                cards.header(["## ترتيب الأعضاء", f"{title}\nلشهر **{month_label}**"], avatar),
                cards.sep(2),
                cards.text("\n".join(lines)),
            ]

        options = [
            discord.SelectOption(label="حسب إجمالي المبلغ", value="amount", emoji="💰",
                                 description="ترتيب الأعضاء حسب قيمة أعمالهم"),
            discord.SelectOption(label="حسب عدد الفصول", value="chapters", emoji="📑",
                                 description="ترتيب الأعضاء حسب عدد الفصول"),
            discord.SelectOption(label="حسب تخصص محدد", value="by_type", emoji="🛠️",
                                 description="اختر تخصصًا ثم اعرض أبطاله"),
        ]
        children.append(cards.sep())
        children.append(cards.make_select("تغيير معيار الترتيب...", options, self._filter_selected))
        if self.back is not None:
            children.append(cards.sep())
            children.append(self._back_row())
        return children

    async def _filter_selected(self, interaction: discord.Interaction):
        value = interaction.data['values'][0]
        self.sort_by = value
        self.current_type = None
        await self.refresh(interaction)

    async def _type_selected(self, interaction: discord.Interaction):
        self.current_type = interaction.data['values'][0]
        self.sort_by = "by_type"
        await self.refresh(interaction)


# ═══════════════════════════════════════════════════════════════
# 👤 تفاصيل عضو دقيقة — تُفتح من قائمة /الأعضاء
# ═══════════════════════════════════════════════════════════════
class MemberDetailView(BackNav, ui.LayoutView):
    """البطاقة الدقيقة الكاملة لعضو واحد: إجماليات، تفصيل أعمال بأشرطة،
    تفصيل تخصصات، آخر السجلات — وصورة العضو في الرأس."""

    def __init__(self, row, guild, currency, entries, back=None, focus_specialty=None):
        super().__init__(timeout=600.0)
        self.row = row
        self.guild = guild
        self.currency = currency or '$'
        self.entries = entries
        self.back = back
        self.focus_specialty = focus_specialty
        self.rebuild()

    @classmethod
    async def create(cls, row, guild, currency, back=None, focus_specialty=None):
        records = await load_visible_records()
        entries = records.get(row["user_id"], [])
        if focus_specialty:
            entries = [e for e in entries if e.get("work_type") == focus_specialty]
        return cls(row, guild, currency, entries, back, focus_specialty)

    def _blocks(self) -> str:
        cur = self.currency
        r = self.row
        bonuses = sum(e.get("total", 0) for e in self.entries if e.get("work_type") == "مكافأة")
        deductions = sum(abs(e.get("total", 0)) for e in self.entries if e.get("work_type") == "خصم")
        work_entries = [e for e in self.entries if e.get("work_type") not in ("مكافأة", "خصم")]

        # 1) الإجماليات — كل رقم في سطر مستقل
        scope = " — في التخصص المحدد" if self.focus_specialty else ""
        totals = "\n".join([
            "### الإجماليات" + scope,
            f"**الفصول:** {r['chapters']}",
            f"**الأعمال:** {r['works_count']}",
            f"**السجلات:** {len(self.entries)}",
            f"**قيمة الأعمال:** {cur}{r['total_works']:,.2f}",
            f"**المكافآت:** {cur}{bonuses:,.2f}",
            f"**الخصومات:** {cur}{deductions:,.2f}",
            f"**💰 الصافي النهائي:** {cur}{r['net_total']:,.2f}",
        ])

        blocks = [totals]

        # 2) تفصيل الأعمال بأشرطة
        works_stats = defaultdict(lambda: {"c": 0, "t": 0.0})
        for e in work_entries:
            s = works_stats[e.get("work_name", "غير محدد")]
            s["c"] += 1
            s["t"] += e.get("total", 0)
        if works_stats:
            max_c = max(s["c"] for s in works_stats.values())
            lines = [f"• **{w}** — {cards.progress_bar(s['c'], max_c)} **{s['c']}** فصول — {cur}{s['t']:,.2f}"
                     for w, s in sorted(works_stats.items(), key=lambda kv: -kv[1]["c"])]
            blocks.append("### تفصيل الأعمال\n" + "\n".join(lines))

        # 3) تفصيل التخصصات
        types_stats = defaultdict(lambda: {"c": 0, "t": 0.0})
        for e in work_entries:
            s = types_stats[e.get("work_type", "غير محدد")]
            s["c"] += 1
            s["t"] += e.get("total", 0)
        if types_stats:
            max_c = max(s["c"] for s in types_stats.values())
            lines = [f"• **{t.replace('_', ' ').title()}** — {cards.progress_bar(s['c'], max_c)} **{s['c']}** فصول — {cur}{s['t']:,.2f}"
                     for t, s in sorted(types_stats.items(), key=lambda kv: -kv[1]["c"])]
            blocks.append("### تفصيل التخصصات\n" + "\n".join(lines))

        # 4) آخر السجلات (الأحدث أولًا)
        recent = sorted([e for e in self.entries if entry_datetime(e)],
                        key=lambda e: entry_datetime(e), reverse=True)[:5]
        if recent:
            lines = []
            for e in recent:
                dt = entry_datetime(e)
                stamp = dt.strftime("%m-%d") if dt else ""
                lines.append(f"• **فصل {e.get('chapter', '؟')}** — {e.get('work_name', '؟')} — "
                             f"{e.get('work_type', '؟')} — {cur}{e.get('total', 0):.2f}"
                             + (f"\n  -# {stamp}" if stamp else ""))
            blocks.append("### آخر السجلات\n" + "\n".join(lines))

        return "\n\n".join(blocks)

    def rebuild(self):
        self.clear_items()
        member = self.guild.get_member(int(self.row["user_id"])) if self.guild else None
        avatar = _member_avatar(member)
        who = member.mention if member else self.row["mention"]
        title = ("تفاصيل العضو في التخصص" if self.focus_specialty else "تفاصيل العضو")
        subtitle = (f"{who} — تخصص **{self.focus_specialty.replace('_', ' ').title()}**"
                    if self.focus_specialty else who)
        children: list = [
            cards.header([f"## {title}", subtitle], avatar),
            cards.sep(2),
            cards.text(cards.clamp(self._blocks(), 3600)),
        ]
        if self.back is not None:
            children += [cards.sep(), self._back_row("عودة إلى القائمة")]
        children += [cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
        self.add_item(cards.container(cards.ACCENT_GOLD, *children))


# ═══════════════════════════════════════════════════════════════
# 👥 /الأعضاء — القائمة المريحة: سطر واحد لكل عضو + اختيار عضو
#   من القائمة المنسدلة يفتح تفاصيله الدقيقة.
# ═══════════════════════════════════════════════════════════════
class MembersHubView(BackNav, ui.LayoutView):
    def __init__(self, rows, guild, currency, title="الأعضاء والمستحقات",
                 back=None, per_page=8, focus_specialty=None):
        super().__init__(timeout=600.0)
        self.rows = rows
        self.guild = guild
        self.currency = currency or '$'
        self.title = title
        self.back = back
        self.per_page = per_page
        self.focus_specialty = focus_specialty
        self.page = 0
        self.total_pages = max(1, (len(rows) + per_page - 1) // per_page)
        self.rebuild()

    def accent(self):
        return cards.ACCENT_GOLD

    def _summary_text(self) -> str:
        total_net = sum(r["net_total"] for r in self.rows)
        total_ch = sum(r["chapters"] for r in self.rows)
        with_work = sum(1 for r in self.rows if not r.get("no_work"))
        return (f"**الأعضاء:** {len(self.rows)}\n"
                f"**من لهم عمل هذا الشهر:** {with_work}\n"
                f"**الفصول المحتسبة:** {total_ch}\n"
                f"**💰 الصافي الإجمالي:** {self.currency}{total_net:,.2f}")

    def _member_line(self, i, row) -> str:
        who = f"<@{row['user_id']}>"
        if row.get("no_work"):
            return (f"{cards.rank_prefix(i)} {who}\n"
                    f"-# لا يوجد عمل أو فصول هذا الشهر")
        return (f"{cards.rank_prefix(i)} {who}\n"
                f"-# {row['chapters']} فصل • {row['works_count']} أعمال • 💰 {self.currency}{row['net_total']:,.2f}")

    def _options(self):
        start = self.page * self.per_page
        page_rows = self.rows[start:start + self.per_page]
        options = []
        for row in page_rows:
            member = self.guild.get_member(int(row["user_id"])) if self.guild else None
            name = member.display_name if member else row["display"]
            desc = ("لا يوجد عمل هذا الشهر" if row.get("no_work")
                    else f"{row['chapters']} فصول • {self.currency}{row['net_total']:,.2f}")
            options.append(discord.SelectOption(
                label=cards.clamp(name, 100),
                value=row["user_id"],
                description=cards.clamp(desc, 100),
                emoji="👤",
            ))
        return options

    def rebuild(self):
        self.clear_items()
        children: list = [
            cards.header([f"## {self.title}",
                          "اختر عضواً من القائمة لعرض تفاصيله الدقيقة."], _bot_avatar()),
            cards.sep(2),
            cards.text(self._summary_text()),
            cards.sep(),
        ]
        start = self.page * self.per_page
        page_rows = self.rows[start:start + self.per_page]
        if page_rows:
            blocks = [self._member_line(start + k, row) for k, row in enumerate(page_rows, 1)]
            children.append(cards.text("\n".join(blocks)))
            children.append(cards.sep())
            children.append(cards.make_select(
                "اختر عضواً لعرض تفاصيله الدقيقة...", self._options(), self._member_selected))
        else:
            children.append(cards.text("*لا يوجد أعضاء لعرضهم.*"))
        if self.total_pages > 1:
            children += [cards.sep(), cards.pager_row(self.page, self.total_pages, self._prev, self._next)]
        if self.back is not None:
            children += [cards.sep(), self._back_row("عودة إلى لوحة التحكم")]
        children += [cards.sep(), cards.text(f"-# الترتيب حسب الصافي • {cards.BOT_SIGNATURE}")]
        self.add_item(cards.container(self.accent(), *children))

    async def refresh(self, interaction: discord.Interaction):
        self.rebuild()
        await interaction.response.edit_message(view=self)

    async def _prev(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        await self.refresh(interaction)

    async def _next(self, interaction: discord.Interaction):
        self.page = min(self.total_pages - 1, self.page + 1)
        await self.refresh(interaction)

    async def _member_selected(self, interaction: discord.Interaction):
        uid = interaction.data['values'][0]
        row = next((r for r in self.rows if r["user_id"] == uid), None)
        if row is None:
            await interaction.response.defer()
            return
        detail = await MemberDetailView.create(
            row, self.guild, self.currency, back=self, focus_specialty=self.focus_specialty)
        await interaction.response.edit_message(view=detail)


class SpecialtyMembersView(MembersHubView):
    """نفس قائمة الأعضاء لكن مركزة على تخصص واحد."""

    def __init__(self, rows, guild, currency, specialty, back=None):
        self.specialty = specialty
        super().__init__(rows, guild, currency,
                         title=f"أعضاء تخصص: {specialty.replace('_', ' ').title()}",
                         back=back, per_page=8, focus_specialty=specialty)

    def _summary_text(self) -> str:
        total_net = sum(r["net_total"] for r in self.rows)
        total_ch = sum(r["chapters"] for r in self.rows)
        return (f"**الأعضاء:** {len(self.rows)}\n"
                f"**الفصول في التخصص:** {total_ch}\n"
                f"**💰 الصافي الإجمالي:** {self.currency}{total_net:,.2f}")

    def _member_line(self, i, row) -> str:
        who = f"<@{row['user_id']}>"
        return (f"{cards.rank_prefix(i)} {who}\n"
                f"-# {row['chapters']} فصل في التخصص • 💰 {self.currency}{row['net_total']:,.2f}")


# ═══════════════════════════════════════════════════════════════
# 📊 عارض الإحصائيات التفاعلي — أزرار الأقسام
# ═══════════════════════════════════════════════════════════════
class StatsView(ui.LayoutView):
    def __init__(self, stat_doc, bot_member, currency, guild: discord.Guild, back=None):
        super().__init__(timeout=600.0)
        self.stat_doc = stat_doc
        self.bot_member = bot_member
        self.currency = currency if currency else '$'
        self.guild = guild
        self.back = back
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
        # كل الأزرار رمادية — الزر النشط يظهر معطلاً (مُظللاً) ليعرف المستخدم مكانه
        return cards.row(
            cards.make_button("الرئيسية", style=discord.ButtonStyle.secondary,
                              callback=self._overview_callback, disabled=self.current_page == "overview"),
            cards.make_button("التخصصات", style=discord.ButtonStyle.secondary,
                              callback=self._types_callback, disabled=self.current_page == "types"),
            cards.make_button("زمني", style=discord.ButtonStyle.secondary,
                              callback=self._time_callback, disabled=self.current_page == "time"),
            cards.make_button("الأفضل", style=discord.ButtonStyle.secondary,
                              callback=self._enter_top_mode),
        )

    def _build_children(self) -> list:
        avatar = _member_avatar(self.bot_member)
        month_label = "الشهر الحالي"
        children: list = [
            cards.header(["## لوحة الإحصائيات", f"مؤشرات **{month_label}** المحدثة تلقائيًا."], avatar),
            cards.sep(2),
        ]
        children += self._page_children()
        children += [cards.sep(), self._tabs_row()]
        if self.back is not None:
            children += [cards.sep(), cards.row(cards.secondary_btn("عودة إلى لوحة التحكم", self._back_cb, emoji="↩"))]
        return children

    async def _back_cb(self, interaction: discord.Interaction):
        parent = self.back
        if callable(parent):
            result = parent()
            if hasattr(result, "__await__"):
                result = await result
            parent = result
        if parent is None:
            await interaction.response.defer()
            return
        await interaction.response.edit_message(view=parent)

    def _page_children(self) -> list:
        if self.current_page == "types":
            return self._types_body()
        if self.current_page == "time":
            return self._time_body()
        if self.current_page == "top":
            return [cards.text("*اختر معيار الترتيب من القائمة أدناه.*")]
        return self._overview_body()

    def _overview_body(self):
        total_entries = self.stat_doc.get("total_entries", 0)
        total_amount = self.stat_doc.get("total_amount", 0)
        active = len(get_top_members_dict(self.stat_doc))
        return [
            cards.text(
                f"**الفصول:** {total_entries}\n"
                f"**💰 إجمالي المبالغ:** {self.currency}{total_amount:,.2f}\n"
                f"**الأعضاء النشطون:** {active}"
            ),
        ]

    def _types_body(self):
        total_entries = self.stat_doc.get("total_entries", 0)
        type_counts = self.stat_doc.get("type_counts", {})
        if not type_counts:
            return [cards.text("لا توجد بيانات تخصصات بعد.")]
        lines = []
        for k, v in sorted(type_counts.items(), key=lambda kv: -kv[1]):
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
                f"**اليوم** — {daily['entries']} فصل • 💰 {self.currency}{daily['amount']:,.2f}\n"
                f"**الأسبوع** — {weekly['entries']} فصل • 💰 {self.currency}{weekly['amount']:,.2f}\n"
                f"**الشهر** — {monthly['entries']} فصل • 💰 {self.currency}{monthly['amount']:,.2f}\n"
                f"**الإجمالي الكلي** — {total_entries} فصل • 💰 {self.currency}{total_amount:,.2f}"
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
        top = await TopView.create(self.stat_doc, self.guild, self.currency, back=self)
        await interaction.response.edit_message(view=top)


# ═══════════════════════════════════════════════════════════════
# 🛠️ اختيار التخصص من لوحة التحكم
# ═══════════════════════════════════════════════════════════════
class SpecialtyPickView(BackNav, ui.LayoutView):
    def __init__(self, guild: discord.Guild, back=None):
        super().__init__(timeout=600.0)
        self.guild = guild
        self.back = back
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        options = [
            discord.SelectOption(label=cards.clamp(s.replace('_', ' ').title(), 100), value=s, emoji="🛠️")
            for s in sorted(PRICES.keys())
        ]
        children: list = [
            cards.header(["## أعضاء تخصص",
                          "اختر التخصص لعرض أعضائه ومستحقاتهم فيه مرتبين حسب الفصول."], _bot_avatar()),
            cards.sep(2),
        ]
        if options:
            children.append(cards.text(f"**التخصصات المعتمدة حاليًا:** {len(options)}"))
            children.append(cards.sep())
            children.append(cards.make_select("اختر التخصص...", options, self._picked))
        else:
            children.append(cards.text("لا توجد تخصصات مفعّلة بعد — يضيفها المشرفون من /اضافة_تخصص."))
        if self.back is not None:
            children += [cards.sep(), self._back_row("عودة إلى لوحة التحكم")]
        children += [cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
        self.add_item(cards.container(cards.ACCENT_GOLD, *children))

    async def _picked(self, interaction: discord.Interaction):
        specialty = interaction.data['values'][0]
        await interaction.response.defer()
        try:
            records = await load_visible_records()
            filtered = {}
            for uid, entries in records.items():
                matched = [e for e in entries if e.get("work_type") == specialty]
                if matched:
                    filtered[uid] = matched
            if not filtered:
                await interaction.message.edit(view=cards.info_card(
                    "لا يوجد أعضاء", [f"لا يوجد أعضاء مسجلون في تخصص `{specialty}`."],
                    avatar_url=_bot_avatar()))
                return
            rows = await _build_member_finance_rows(filtered, self.guild)
            rows.sort(key=lambda row: (row["chapters"], row["net_total"]), reverse=True)
            view = SpecialtyMembersView(rows, self.guild, SETTINGS.get('currency', '$'),
                                        specialty, back=self.back)
            await interaction.message.edit(view=view)
        except Exception as e:
            await interaction.message.edit(view=cards.error_card(
                "تعذر فتح القسم", [f"`{str(e)[:200]}`"], avatar_url=_bot_avatar()))


# ═══════════════════════════════════════════════════════════════
# 🖥️ لوحة التحكم — كل زر ينفّذ أمره مباشرة في مكان اللوحة
# ═══════════════════════════════════════════════════════════════
class DashboardView(ui.LayoutView):
    def __init__(self, guild: discord.Guild, user):
        super().__init__(timeout=900.0)
        self.guild = guild
        self.user = user

    @classmethod
    async def create(cls, guild: discord.Guild, user):
        self = cls(guild, user)
        await self.rebuild_async()
        return self

    async def rebuild_async(self):
        self.clear_items()
        children = await self.build_children()
        self.add_item(cards.container(cards.ACCENT_GOLD, *children))

    async def _as_back(self):
        """مصنع عودة حي: يبني لوحة جديدة ببيانات محدثة."""
        return await DashboardView.create(self.guild, self.user)

    def _swap(self, factory):
        """مصنع أزرار تُنفّذ: يؤجل التفاعل، يبني القسم، ثم يحرر البطاقة في مكانها."""
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            try:
                child = await factory()
                await interaction.message.edit(view=child)
            except Exception as e:
                try:
                    await interaction.message.edit(view=cards.error_card(
                        "تعذر فتح القسم", [f"حدث خطأ:\n`{str(e)[:200]}`"], avatar_url=_bot_avatar()))
                except Exception:
                    pass
        return callback

    async def _open_members(self):
        records = await load_visible_records()
        rows = await _build_member_finance_rows(records, self.guild, include_all_members=True)
        if not rows:
            return cards.info_card("لا يوجد أعضاء",
                                   ["لا يوجد أعضاء محفوظون بعد — يبدأ العد بأول /تسجيل."],
                                   avatar_url=_bot_avatar())
        return MembersHubView(rows, self.guild, SETTINGS.get('currency', '$'),
                              title="الأعضاء والمستحقات", back=self._as_back)

    async def _open_top(self):
        stat_doc = await get_active_stats_doc()
        return await TopView.create(stat_doc, self.guild, SETTINGS.get('currency', '$'), back=self._as_back)

    async def _open_stats(self):
        stat_doc = await get_active_stats_doc()
        if not stat_doc:
            return cards.info_card("لا توجد إحصائيات",
                                   ["لا توجد إحصائيات لهذا الشهر بعد."], avatar_url=_bot_avatar())
        return StatsView(stat_doc, self.guild.me, SETTINGS.get('currency', '$'),
                         self.guild, back=self._as_back)

    async def _open_payment(self):
        rows, details = await build_payment_rows(self.guild)
        if not rows:
            month_label = await get_month_name(get_active_month_key())
            return cards.info_card("لا توجد سجلات",
                                   [f"لا توجد أي سجلات لشهر **{month_label}**."], avatar_url=_bot_avatar())
        paginator = PaymentReportPaginator(rows, details, self.guild,
                                           SETTINGS.get('currency', '$'), back=self._as_back)
        paginator.month_label = await get_month_name(get_active_month_key())
        return paginator

    async def _open_specialty(self):
        return SpecialtyPickView(self.guild, back=self._as_back)

    async def _open_months(self):
        from commands.months import MonthsHubView
        return await MonthsHubView.create(self.guild, self.user, back=self._as_back)

    async def _open_monthly(self):
        active_key = get_active_month_key()
        records = await load_visible_records(active_key)
        entries = records.get(str(self.user.id), [])
        if not entries:
            async def _back(interaction: discord.Interaction):
                parent = await self._as_back()
                await interaction.response.edit_message(view=parent)
            children = [
                cards.header(["## الملخص الشهري", f"<@{self.user.id}>"], _bot_avatar()),
                cards.sep(2),
                cards.text(f"لا يوجد عمل مسجل لك في **{await get_month_name(active_key)}** حتى الآن."),
                cards.sep(),
                cards.row(cards.secondary_btn("عودة إلى لوحة التحكم", _back, emoji="↩")),
                cards.sep(),
                cards.text(f"-# {cards.BOT_SIGNATURE}"),
            ]
            return cards.Card(cards.ACCENT_GOLD, *children)
        # نفس البطاقة المستخدمة في /ملخص_شهري + زر رجوع إلى اللوحة
        return build_monthly_summary_card(self.user, entries,
                                          SETTINGS.get('currency', '$'), _bot_avatar(),
                                          back_factory=self._as_back,
                                          month_label=await get_month_name(active_key))

    async def build_children(self) -> list:
        avatar = _bot_avatar()
        currency = SETTINGS.get('currency', '$') or '$'
        active_key = get_active_month_key()
        month_label = await get_month_name(active_key)
        records = await load_visible_records(active_key)
        rows = await _build_member_finance_rows(records, self.guild, include_all_members=True)
        works = await load_works()
        isolated_count = len(get_isolated_work_names(works))
        total_chapters = sum(r["chapters"] for r in rows)
        total_net = sum(r["net_total"] for r in rows)
        with_work = sum(1 for r in rows if not r.get("no_work"))

        # صدارة الأعضاء — التاج للمركز الأول فقط، وكل عضو في سطرين مستقلين
        work_rows = [r for r in rows if not r.get("no_work")]
        if work_rows:
            preview_lines = []
            for k, r in enumerate(work_rows[:3], 1):
                preview_lines.append(f"{cards.rank_prefix(k)} {r['mention']}")
                preview_lines.append(f"-# {r['chapters']} فصل • 💰 {currency}{r['net_total']:,.2f}")
            preview = "\n".join(preview_lines)
        else:
            preview = "• لا توجد بيانات بعد."

        pulse = (
            f"**الشهر الحالي:** {month_label} (`{active_key}`)\n"
            f"**الأعضاء المحفوظون:** {len(rows)}\n"
            f"**من لهم عمل هذا الشهر:** {with_work}\n"
            f"**الفصول المحتسبة:** {total_chapters}\n"
            f"**💰 إجمالي المستحقات:** {currency}{total_net:,.2f}\n"
            f"**أعمال معزولة:** {isolated_count}"
        )

        return [
            cards.header(["## لوحة التحكم",
                          f"<@{self.user.id}> — كل الأدوات بضغطة زر، والأزرار **تُنفّذ مباشرة**."], avatar),
            cards.sep(2),
            cards.text("### نبضة الشهر\n" + pulse),
            cards.sep(),
            cards.text("### صدارة الأعضاء\n" + preview),
            cards.sep(),
            cards.row(
                cards.secondary_btn("الأعضاء", self._swap(self._open_members)),
                cards.secondary_btn("التوب", self._swap(self._open_top)),
                cards.secondary_btn("الإحصائيات", self._swap(self._open_stats)),
            ),
            cards.row(
                cards.secondary_btn("تقرير الدفع", self._swap(self._open_payment)),
                cards.secondary_btn("أعضاء تخصص", self._swap(self._open_specialty)),
                cards.secondary_btn("الشهور", self._swap(self._open_months)),
            ),
            cards.row(
                cards.secondary_btn("ملخص شهري", self._swap(self._open_monthly)),
            ),
            cards.sep(),
            cards.text(f"-# {cards.BOT_SIGNATURE}"),
        ]


# ═══════════════════════════════════════════════════════════════
# 1️⃣ أمر الأعمال
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="الأعمال", description="عرض جميع الأعمال والاعضاء")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def projects_report(interaction: discord.Interaction):
    if not channel_allowed(interaction):
        await interaction.response.send_message(
            view=cards.channel_card(SETTINGS.get("allowed_channels", []), _bot_avatar()), ephemeral=True)
        return

    works_info = await get_works_info(interaction.guild)
    if not works_info:
        await interaction.response.send_message(view=cards.info_card(
            "لا توجد أعمال", ["لا توجد أعمال مسجلة في القائمة."], avatar_url=_bot_avatar()), ephemeral=True)
        return

    view = WorksPaginator(works_info, interaction.guild)
    await interaction.response.send_message(view=view)


# ═══════════════════════════════════════════════════════════════
# 2️⃣ احصائيات (نظام تفاعلي كامل)
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="احصائيات", description="عرض إحصائيات متقدمة")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def stats(interaction: discord.Interaction):
    stat_doc = await get_active_stats_doc()
    if not stat_doc:
        await interaction.response.send_message(view=cards.info_card(
            "لا توجد إحصائيات", ["لا توجد إحصائيات لهذا الشهر بعد."], avatar_url=_bot_avatar()), ephemeral=True)
        return

    view = StatsView(stat_doc, interaction.guild.me, SETTINGS.get('currency', '$'),
                     interaction.guild)
    await interaction.response.send_message(view=view)


# ═══════════════════════════════════════════════════════════════
# 2.5️⃣ /توب (ترتيب الأعضاء المستقل) — مُصلح بالكامل
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="توب", description="عرض ترتيب الأعضاء حسب معايير مختلفة")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def top_members(interaction: discord.Interaction):
    stat_doc = await get_active_stats_doc()
    currency = SETTINGS.get('currency', '$') or '$'
    # ⚠️ create() تبني البطاقة كاملة قبل الإرسال — لا رسائل فارغة أبدًا
    view = await TopView.create(stat_doc, interaction.guild, currency, back=None)
    await interaction.response.send_message(view=view)


# ═══════════════════════════════════════════════════════════════
# 2.7️⃣ /الأعضاء + /اعضاء_تخصص — القائمة المريحة + التفاصيل الدقيقة
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="الأعضاء", description="قائمة الأعضاء ومستحقاتهم مع تفاصيل دقيقة لكل عضو")
@app_commands.describe(بحث="بحث اختياري باسم العضو أو معرفه")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def registered_members(interaction: discord.Interaction, بحث: str = None):
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "الأعضاء")
        await interaction.response.send_message(view=cards.permission_card(_bot_avatar()), ephemeral=True)
        return

    records = await load_visible_records()
    rows = await _build_member_finance_rows(records, interaction.guild, بحث, include_all_members=True)
    if not rows:
        await interaction.response.send_message(view=cards.info_card(
            "لا يوجد أعضاء", ["لا يوجد أعضاء محفوظون بعد — يبدأ العد بأول /تسجيل."], avatar_url=_bot_avatar()), ephemeral=True)
        return
    title = "الأعضاء والمستحقات"
    if بحث:
        title += f" • بحث: {بحث}"
    view = MembersHubView(rows, interaction.guild, SETTINGS.get('currency', '$'), title)
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
    rows = await _build_member_finance_rows(filtered_records, interaction.guild)
    rows.sort(key=lambda row: (row["chapters"], row["net_total"]), reverse=True)
    if not rows:
        await interaction.response.send_message(view=cards.info_card(
            "لا يوجد أعضاء", [f"لا يوجد أعضاء مسجلون في تخصص `{specialty}`."], avatar_url=_bot_avatar()), ephemeral=True)
        return
    view = SpecialtyMembersView(rows, interaction.guild, SETTINGS.get('currency', '$'), specialty)
    await interaction.response.send_message(view=view)


# ═══════════════════════════════════════════════════════════════
# 3️⃣ أعمالي
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="أعمالي", description="عرض أعمالك مجمعة مع المكافآت والخصومات")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def my_works_slash(interaction: discord.Interaction):
    if not channel_allowed(interaction):
        await interaction.response.send_message(
            view=cards.channel_card(SETTINGS.get("allowed_channels", []), _bot_avatar()), ephemeral=True)
        return

    records = await load_visible_records()
    user_id = str(interaction.user.id)
    if user_id not in records or not records[user_id]:
        await interaction.response.send_message(view=cards.info_card(
            "ليس لديك أي شغل", ["لم تسجل أي فصول بعد — ابدأ بأمر /تسجيل."],
            avatar_url=_member_avatar(interaction.user)), ephemeral=True)
        return

    works, bonuses, deductions = _categorize_records(records[user_id])
    view = WorkSummarySelectView(
        works, bonuses, deductions,
        member=interaction.user,
        user_id=user_id,
        currency=SETTINGS.get('currency', '$'),
        title_prefix="اللوحة الشخصية"
    )
    await interaction.response.send_message(view=view)


@bot.command(name="أعمالي")
@commands.cooldown(1, 5, commands.BucketType.user)
async def my_works_text(ctx):
    records = await load_visible_records()
    user_id = str(ctx.author.id)
    if user_id not in records or not records[user_id]:
        await ctx.send("ليس لديك أي شغل مسجل بعد — ابدأ بأمر /تسجيل.")
        return

    works, bonuses, deductions = _categorize_records(records[user_id])
    view = WorkSummarySelectView(
        works, bonuses, deductions,
        member=ctx.author,
        user_id=user_id,
        currency=SETTINGS.get('currency', '$'),
        title_prefix="اللوحة الشخصية"
    )
    await ctx.send(view=view)


# ═══════════════════════════════════════════════════════════════
# 4️⃣ شغل — الصورة المصغرة لصورة العضو المعنيّ دائمًا
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="شغل", description="عرض شغل عضو مجمّع مع المكافآت والخصومات")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def show_work_slash(interaction: discord.Interaction, member: discord.Member = None):
    if not channel_allowed(interaction):
        await interaction.response.send_message(
            view=cards.channel_card(SETTINGS.get("allowed_channels", []), _bot_avatar()), ephemeral=True)
        return

    target = member or interaction.user
    records = await load_visible_records()
    user_id = str(target.id)
    if user_id not in records or not records[user_id]:
        await interaction.response.send_message(view=cards.error_card(
            "لا يوجد شغل", [f"لا يوجد شغل مسجل للعضو {target.mention}."],
            avatar_url=_member_avatar(target)), ephemeral=True)
        return

    works, bonuses, deductions = _categorize_records(records[user_id])
    view = WorkSummarySelectView(
        works, bonuses, deductions,
        member=target,
        user_id=user_id,
        currency=SETTINGS.get('currency', '$'),
        title_prefix="ملخص شغل"
    )
    await interaction.response.send_message(view=view)


@bot.command(name="شغل")
@commands.cooldown(1, 5, commands.BucketType.user)
async def show_work_text(ctx, member: discord.Member = None):
    member = member or ctx.author
    records = await load_visible_records()
    user_id = str(member.id)
    if user_id not in records or not records[user_id]:
        await ctx.send(f"لا يوجد شغل مسجل للعضو {member.mention}.")
        return

    works, bonuses, deductions = _categorize_records(records[user_id])
    view = WorkSummarySelectView(
        works, bonuses, deductions,
        member=member,
        user_id=user_id,
        currency=SETTINGS.get('currency', '$'),
        title_prefix="ملخص شغل"
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


async def _build_member_finance_rows(records, guild, search: str = None, include_all_members: bool = False):
    """النسخة الكاملة: تحل اسم كل عضو (نك نيم السيرفر عبر fetch عند الحاجة)
    ويمكنها ضم كل الأعضاء المحفوظين حتى أصحاب لا عمل في هذا الشهر (no_work)."""
    members_docs = {}
    if include_all_members:
        members_docs = await load_members()
    merged = dict(records)
    for uid in members_docs.keys():
        merged.setdefault(uid, [])
    rows = []
    search_text = search.lower().strip() if search else None
    for user_id, entries in merged.items():
        works, bonuses, deductions = _categorize_records(entries)
        work_entries = [entry for work_entries in works.values() for entry in work_entries]
        total_works = sum(entry.get("total", 0) for entry in work_entries)
        total_bonus = sum(entry.get("total", 0) for entry in bonuses)
        total_deduct = sum(abs(entry.get("total", 0)) for entry in deductions)
        net_total = total_works + total_bonus - total_deduct
        username_hint = _member_name_from_entries(entries) or members_docs.get(user_id, {}).get("username")
        display = await resolve_display_name(guild, user_id, username_hint)
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
            "no_work": len(entries) == 0,
        })
    # العاملون أولاً (الأعلى صافيًا)، ثم أصحاب «لا عمل هذا الشهر»
    return sorted(rows, key=lambda row: (row["no_work"], -row["net_total"], -row["chapters"]))


# ═══════════════════════════════════════════════════════════════
# 5️⃣ لوحة التحكم — أزرار تنفّذ لا أزرار توجّه
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="لوحة_التحكم", description="لوحة تحكم تفاعلية للمشرفين — الأزرار تُنفّذ مباشرة")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def dashboard(interaction: discord.Interaction):
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "لوحة_التحكم")
        await interaction.response.send_message(view=cards.permission_card(_bot_avatar()), ephemeral=True)
        return

    view = await DashboardView.create(interaction.guild, interaction.user)
    await interaction.response.send_message(view=view)


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
            "سجل العمليات", ["لا توجد سجلات بعد."], avatar_url=_bot_avatar()), ephemeral=True)
        return

    bullets = []
    for log in logs:
        target_part = f" • على <@{log.get('target_id')}>" if log.get('target_id') else ""
        bullets.append(
            f"• **{log.get('action', 'غير معروف')}**\n"
            f"-# بواسطة <@{log.get('moderator_id')}>{target_part}\n"
            f"-# {cards.clamp(str(log.get('details')), 120)}\n"
            f"-# {str(log.get('timestamp'))[:19]}"
        )
    children: list = [
        cards.header(["## سجل العمليات", f"**{len(logs)}** عملية أحدث أولًا."], _bot_avatar()),
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
    records = await load_visible_records(None)
    user_id = str(interaction.user.id)
    if user_id not in records:
        await interaction.response.send_message(view=cards.info_card(
            "لا توجد سجلات", ["ليس لديك أي سجلات."], avatar_url=_member_avatar(interaction.user)), ephemeral=True)
        return

    week_ago = datetime.utcnow() - timedelta(days=7)
    week_entries = [
        e for e in records[user_id]
        if (dt := entry_datetime(e)) is not None and dt > week_ago
    ]
    if not week_entries:
        await interaction.response.send_message(view=cards.info_card(
            "لا يوجد نشاط", ["لا يوجد فصول خلال الأسبوع الماضي."],
            avatar_url=_member_avatar(interaction.user)), ephemeral=True)
        return

    total = sum(e.get("total", 0) for e in week_entries)
    currency = SETTINGS.get('currency', '$') or '$'
    works_count = defaultdict(int)
    for e in week_entries:
        works_count[e.get("work_name", "غير محدد")] += 1
    breakdown = "\n".join(f"• **{w}:** {c} فصول" for w, c in sorted(works_count.items(), key=lambda kv: -kv[1]))
    children: list = [
        cards.member_header(["## التقرير الأسبوعي", f"<@{interaction.user.id}>"], interaction.user),
        cards.sep(2),
        cards.text(
            f"### الحصيلة\n**المهام:** {len(week_entries)}\n**💰 المجموع:** {currency}{total:,.2f}"
        ),
        cards.sep(),
        cards.text("### التفصيل\n" + breakdown),
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
    avatar = _member_avatar(interaction.user)
    records = await load_records()
    user_id = str(interaction.user.id)
    if user_id not in records or not records[user_id]:
        await interaction.response.send_message(view=cards.info_card(
            "لا توجد سجلات", ["لا يوجد سجلات."], avatar_url=avatar), ephemeral=True)
        return

    last = records[user_id][-1]
    changed = []
    if العمل:
        last["work_name"] = العمل
        changed.append(f"✓ العمل ← {العمل}")
    if الفصل:
        last["chapter"] = الفصل
        changed.append(f"✓ الفصل ← {الفصل}")
    if التخصص:
        norm_type = map_type(التخصص)
        if norm_type not in PRICES:
            await interaction.response.send_message(view=cards.error_card(
                "التخصص غير صحيح", [f"التخصص `{التخصص}` غير موجود في القائمة."], avatar_url=avatar), ephemeral=True)
            return
        last["work_type"] = norm_type
        last["total"] = PRICES[norm_type]
        changed.append(f"✓ التخصص ← {norm_type}")
    if ملاحظات is not None:
        last["notes"] = ملاحظات
        changed.append("✓ الملاحظات ← محدثة")

    await save_records(records)
    await update_stats()
    detail = "\n".join(changed) or "لم تحدد أي تغيير."
    await interaction.response.send_message(view=cards.success_card(
        "تم تعديل آخر سجل",
        [f"<@{interaction.user.id}>", detail],
        avatar_url=avatar), ephemeral=True)
