"""!تسجيل — التسجيل التفاعلي بالبريفكس: يختار العضو فقط، والبوت يقوده خطوة خطوة.
نفس مسار /تسجيل بالسلاش ونفس الإيصال بالضبط، لكن بلا كتابة معاملات:
  1) اختيار العمل من قائمة منسدلة.
  2) إرسال نطاق الفصول في المحادثة (مثال: 1-5).
  3) اختيار التخصصات من قائمة منسدلة.
  4) بطاقة تأكيد بالإجمالي التقديري → تسجيل فوري وإيصال جاهز.
جلسة واحدة لكل عضو في كل قناة، وتنتهي تلقائيًا بعد دقيقتين من الخمول.
"""
import asyncio
from datetime import datetime, timedelta
import discord
from discord.ext import commands
from state import bot
from helpers.core import (
    SETTINGS, PRICES, load_records, save_records, load_works,
    get_work, is_work_isolated, filter_paid_chapters,
    parse_chapter_range, is_duplicate, get_specialty_price,
    update_stats, upsert_member, get_active_month_key,
)
from azora.gating import registration_blockers, get_azora_link, unpublished_chapters, normalize_chapter
from ui import cards

# جلسات التسجيل النشطة: key=(guild_id, user_id, channel_id) -> WizardSession
_sessions: dict = {}
IDLE_SECONDS = 120


def _bot_avatar() -> str | None:
    return bot.user.display_avatar.url if bot.user else None


def _member_avatar(member) -> str | None:
    try:
        return member.display_avatar.url if member else None
    except Exception:
        return None


def allowed_types_for(work: dict) -> list[str]:
    """التخصصات المتاحة لعمل محدد (الخاصة إن وجدت وإلا العامة)."""
    if work and isinstance(work.get("custom_prices"), dict) and work["custom_prices"]:
        return list(work["custom_prices"].keys())
    return list(PRICES.keys())


def _page_of(items: list, page: int, per: int) -> tuple[list, int]:
    """تقطيع قائمة لصفحات — (عناصر الصفحة, عدد الصفحات الكلي)."""
    total = max(1, (len(items) + per - 1) // per)
    page = min(max(0, page), total - 1)
    return items[page * per: (page + 1) * per], total


class WizardSession:
    PER_PAGE = 25  # حد ديسكورد للقائمة المنسدلة — فوقه نظام صفحات

    def __init__(self, member: discord.Member, guild_id: int, channel_id: int):
        self.member = member
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.message = None             # بطاقة البوت الحية
        self.step = "pick_work"         # pick_work | chapters | types | confirm | notes
        self.page = 0                   # صفحة قائمة اختيار العمل
        self.work = None
        self.chapters_list = []
        self.paid_chapters = []
        self.free_count = 0
        self.types = []
        self.notes = None
        self.expires = datetime.now() + timedelta(seconds=IDLE_SECONDS)
        self.timer = None

    # ── إدارة المهلة ──
    def touch(self):
        self.expires = datetime.now() + timedelta(seconds=IDLE_SECONDS)
        self.arm_timeout()

    def arm_timeout(self):
        if self.timer and not self.timer.done():
            self.timer.cancel()
        self.timer = asyncio.create_task(self._timeout())

    async def _timeout(self):
        await asyncio.sleep(IDLE_SECONDS)
        key = (self.guild_id, self.member.id, self.channel_id)
        if _sessions.get(key) is self:
            _sessions.pop(key, None)
            try:
                await self.message.edit(view=cards.muted_card(
                    "انتهت مهلة التسجيل",
                    ["انتهت دقيقتان دون إكمال — أرسل !تسجيل من جديد متى شئت."],
                    avatar_url=_bot_avatar()))
            except Exception:
                pass

    def cancel_timer(self):
        if self.timer and not self.timer.done():
            self.timer.cancel()

    def _key(self):
        return (self.guild_id, self.member.id, self.channel_id)

    def close(self):
        self.cancel_timer()
        _sessions.pop(self._key(), None)

    # ── حارس ملكية الجلسة ──
    def _not_owner(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id != self.member.id

    async def _deny_other(self, interaction: discord.Interaction):
        await interaction.response.send_message(view=cards.error_card(
            "جلسة عضو آخر",
            ["هذه جلسة تسجيل خاصة بعضو آخر — ابدأ جلستك بأمر !تسجيل."],
            avatar_url=_bot_avatar()), ephemeral=True)

    # ── أفعال القوائم والأزرار ──
    async def _wp_prev(self, interaction: discord.Interaction):
        """صفحة سابقة في قائمة اختيار العمل — التنقل مفتوح للجميع
        (مجرد عرض)، أما الاختيار فمحصور بصاحب الجلسة."""
        self.page = max(0, self.page - 1)
        await interaction.response.edit_message(
            view=cards.Card(cards.ACCENT_GOLD, *await self._work_pick_children()))

    async def _wp_next(self, interaction: discord.Interaction):
        """صفحة تالية في قائمة اختيار العمل — التنقل مفتوح للجميع."""
        self.page += 1
        await interaction.response.edit_message(
            view=cards.Card(cards.ACCENT_GOLD, *await self._work_pick_children()))

    async def select_work(self, interaction: discord.Interaction):
        if self._not_owner(interaction):
            await self._deny_other(interaction)
            return
        work_name = interaction.data['values'][0]
        work = await get_work(work_name)
        if not work or not work.get("active", True) or is_work_isolated(work):
            self.touch()
            await interaction.response.edit_message(
                view=cards.Card(cards.ACCENT_GOLD, *await self._work_pick_children(
                    notice=f"العمل **{work_name}** غير متاح للتسجيل الآن — اختر غيره.")))
            return
        self.work = work
        self.step = "chapters"
        self.page = 0
        self.touch()
        await interaction.response.edit_message(
            view=cards.Card(cards.ACCENT_GOLD, *await self._chapters_children()))

    async def select_types(self, interaction: discord.Interaction):
        if self._not_owner(interaction):
            await self._deny_other(interaction)
            return
        chosen = list(dict.fromkeys(interaction.data['values']))
        allowed = allowed_types_for(self.work)
        chosen = [t for t in chosen if t in allowed]
        if not chosen:
            self.touch()
            await interaction.response.edit_message(
                view=cards.Card(cards.ACCENT_GOLD, *await self._types_children(
                    notice="اختر تخصصًا واحدًا على الأقل.")))
            return
        count = len(self.paid_chapters)
        if len(chosen) == 1:
            self.types = [chosen[0]] * count
        elif len(chosen) == count:
            self.types = chosen
        else:
            self.touch()
            await interaction.response.edit_message(
                view=cards.Card(cards.ACCENT_GOLD, *await self._types_children(
                    notice=f"اخترت **{len(chosen)}** تخصصات وعدد الفصول **{count}**.\n"
                           "إما تخصص واحد للجميع، أو عدد يساوي عدد الفصول بالضبط.")))
            return
        self.step = "confirm"
        self.touch()
        await interaction.response.edit_message(
            view=cards.Card(cards.ACCENT_GOLD, *await self._confirm_children()))

    async def ask_notes(self, interaction: discord.Interaction):
        if self._not_owner(interaction):
            await self._deny_other(interaction)
            return
        self.step = "notes"
        self.touch()

        async def _skip(cb_interaction: discord.Interaction):
            if self._not_owner(cb_interaction):
                await self._deny_other(cb_interaction)
                return
            self.step = "confirm"
            self.touch()
            await cb_interaction.response.edit_message(
                view=cards.Card(cards.ACCENT_GOLD, *await self._confirm_children()))

        children = [
            cards.header(["## إضافة ملاحظة", f"**{self.work['name']}**"],
                         _member_avatar(self.member)),
            cards.sep(2),
            cards.text("أرسل الملاحظة في هذه القناة الآن — أو اضغط تخطي للمرور دون ملاحظة."),
            cards.sep(),
            cards.row(cards.secondary_btn("تخطي", _skip)),
            cards.sep(),
            cards.text(f"-# لديك دقيقتان • {cards.BOT_SIGNATURE}"),
        ]
        await interaction.response.edit_message(view=cards.Card(cards.ACCENT_GOLD, *children))

    async def commit(self, interaction: discord.Interaction):
        if self._not_owner(interaction):
            await self._deny_other(interaction)
            return
        work_name = self.work["name"]
        records = await load_records()
        user_id = str(self.member.id)
        records.setdefault(user_id, [])

        # ── بوابة أزورا النهائية: منشور + لا تكرار فصل+تخصص ──
        blockers = await registration_blockers(
            self.work, self.paid_chapters, self.types, records, self.member.id)
        if blockers:
            self.touch()
            await interaction.response.edit_message(
                view=cards.Card(cards.ACCENT_GOLD, *await self._confirm_children(
                    "**مرفوض — بوابة أزورا:**\n" + "\n".join(blockers[:8]))))
            return

        added_chapters = []
        added_types = []
        duplicates = 0
        month_key = get_active_month_key()
        for ch, t in zip(self.paid_chapters, self.types):
            if is_duplicate(records, user_id, work_name, ch, t):
                duplicates += 1
                continue
            total = await get_specialty_price(work_name, t)
            records[user_id].append({
                "work_name": work_name,
                "chapter": ch,
                "work_type": t,
                "total": total,
                "notes": self.notes or "",
                "timestamp": datetime.utcnow().isoformat(),
                "month_key": month_key,
                "username": self.member.name,
            })
            added_chapters.append(ch)
            added_types.append(t)

        added = len(added_chapters)
        if added == 0:
            self.touch()
            await interaction.response.edit_message(
                view=cards.Card(cards.ACCENT_GOLD, *await self._confirm_children(
                    notice="لم يُسجَّل أي فصل جديد — كل الفصول مكررة أو مجانية.\nأعد اختيار التخصصات أو ألغِ الجلسة.")))
            return

        saved = await save_records(records)
        if not saved:
            await interaction.response.edit_message(view=cards.error_card(
                "تعذر الحفظ",
                ["قاعدة البيانات غير متاحة الآن.",
                 "لم تُسجل بياناتك — **لم يُفقد شيء** — أعد المحاولة بعد قليل."],
                avatar_url=_bot_avatar()))
            return
        await update_stats()
        await upsert_member(self.member.id, self.member.name)

        if added_types and len(set(added_types)) == 1:
            total_amount = added * await get_specialty_price(work_name, added_types[0])
        else:
            total_amount = sum([await get_specialty_price(work_name, t) for t in added_types])

        from commands.register import build_receipt_card
        receipt = build_receipt_card(
            requester=self.member,
            added_by=None,
            work_name=work_name,
            added_chapters=added_chapters,
            total_input_chapters=len(self.chapters_list),
            free_count=self.free_count,
            duplicates_skipped=duplicates,
            filtered_types=added_types,
            total_amount=total_amount,
            notes=self.notes,
            avatar_url=_member_avatar(self.member),
        )
        self.close()
        await self.message.edit(view=receipt)

        notify_channel_id = SETTINGS.get("notify_channel_id")
        if notify_channel_id:
            channel = self.member.guild.get_channel(notify_channel_id)
            if channel:
                try:
                    await channel.send(f"{self.member.mention} أضاف {added} فصول مدفوعة في عمل `{work_name}`")
                except Exception:
                    pass
        threshold = SETTINGS.get("alert_threshold", 10.0)
        currency = SETTINGS.get('currency', '$') or '$'
        total_user = sum(e.get("total", 0) for e in records[user_id])
        if total_user >= threshold:
            try:
                await self.member.send(f"تنبيه: إجمالي شغلك وصل إلى {currency}{total_user:.2f}.")
            except Exception:
                pass

    async def cancel(self, interaction: discord.Interaction):
        if self._not_owner(interaction):
            await self._deny_other(interaction)
            return
        self.close()
        await interaction.response.edit_message(view=cards.muted_card(
            "أُلغيت جلسة التسجيل",
            ["لم يُسجل أي شيء — أرسل !تسجيل متى أردت البدء من جديد."],
            avatar_url=_bot_avatar()))

    # ── بناء محتوى البطاقات (تُعيد قائمة أبناء الحاوية) ──
    async def _work_pick_children(self, notice: str | None = None) -> list:
        works = await load_works()
        usable = [w for w in works if w.get("active", True) and not is_work_isolated(w)]
        page_items, total_pages = _page_of(usable, self.page, self.PER_PAGE)
        children: list = [
            cards.header(["## تسجيل تفاعلي",
                          f"{self.member.mention} — اختر العمل من القائمة."],
                         _member_avatar(self.member)),
            cards.sep(2),
        ]
        if notice:
            children.append(cards.text(notice))
            children.append(cards.sep())
        if not usable:
            children.append(cards.text("لا توجد أعمال متاحة للتسجيل حاليًا — تواصل مع الإدارة."))
        else:
            children.append(cards.text(
                f"-# **الخطوة 1 من 4** — اختيار العمل • **{len(usable)}** عمل متاح"
                + (f" • صفحة {self.page + 1} من {total_pages}" if total_pages > 1 else "")))
            children.append(cards.sep())
            options = []
            for w in page_items:
                ps = w.get("paid_start")
                desc = "كل الفصول مدفوعة" if ps is None else f"يبدأ الدفع من فصل {ps}"
                options.append(discord.SelectOption(
                    label=cards.clamp(w["name"], 100), value=w["name"],
                    description=cards.clamp(desc, 100), emoji="📖"))
            children.append(cards.make_select("اختر العمل...", options, self.select_work))
            if total_pages > 1:
                children.append(cards.sep())
                children.append(cards.pager_row(
                    self.page, total_pages, self._wp_prev, self._wp_next))
        children += [cards.sep(), cards.row(cards.secondary_btn("إلغاء", self.cancel)),
                     cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
        return children

    async def _chapters_children(self) -> list:
        ps = self.work.get("paid_start")
        policy = "كل الفصول مدفوعة" if ps is None else f"الدفع يبدأ من فصل {ps} (الأقدم مجاني)"
        azora_note = ""
        if get_azora_link(self.work):
            link = get_azora_link(self.work)
            from azora import store as _az_store
            cached = await _az_store.get_cached_chapters(link["slug"])
            if cached and cached.get("numbers"):
                latest = max(cached["numbers"], key=normalize_chapter)
                azora_note = (f"\n**هذا العمل مرتبط بأزورا** — يُسمح بالفصول المنشورة فقط، "
                              f"وآخر فصل منشور حاليًا: **{latest}**.")
            else:
                azora_note = ("\n**هذا العمل مرتبط بأزورا** — يُسمح بالفصول المنشورة فقط، "
                              "وكتاش الفصول يُحدّث بالمزامنة الآن.")
        children = [
            cards.header(["## تسجيل تفاعلي", f"العمل: **{self.work['name']}**"],
                         _member_avatar(self.member)),
            cards.sep(2),
            cards.text(
                f"-# **الخطوة 2 من 4** — الفصول\n"
                f"أرسل نطاق الفصول في هذه القناة الآن.\n"
                f"**الأمثلة:** `5` أو `1-5` أو `1,3,7`\n"
                f"**سياسة الدفع هنا:** {policy}"
                f"{azora_note}"
            ),
            cards.sep(),
            cards.row(cards.secondary_btn("إلغاء", self.cancel)),
            cards.sep(),
            cards.text(f"-# لديك دقيقتان • {cards.BOT_SIGNATURE}"),
        ]
        return children

    async def _types_children(self, notice: str | None = None) -> list:
        total_in = len(self.chapters_list)
        kept = len(self.paid_chapters)
        children = [
            cards.header(["## تسجيل تفاعلي",
                          f"**{self.work['name']}** — {cards.progress_line(kept, total_in)}"],
                         _member_avatar(self.member)),
            cards.sep(2),
        ]
        if self.free_count:
            children.append(cards.text(f"تجاهلت **{self.free_count}** فصلًا مجانيًا تلقائيًا."))
            children.append(cards.sep())
        if notice:
            children.append(cards.text(notice))
            children.append(cards.sep())
        options = allowed_types_for(self.work)
        if not options:
            children.append(cards.text("لا توجد تخصصات مفعّلة — تواصل مع الإدارة."))
        else:
            select_options = sorted(
                [discord.SelectOption(label=cards.clamp(t.replace('_', ' ').title(), 100), value=t, emoji="🛠️")
                 for t in options[:25]],
                key=lambda o: o.label)
            children.append(cards.text(
                "-# **الخطوة 3 من 4** — التخصصات\n"
                "اختر **تخصصًا واحدًا** ليعم على كل الفصول،\n"
                "أو اختر **عددًا يساوي عدد الفصول** ليوزع بالترتيب."))
            children.append(cards.sep())
            children.append(cards.make_select("اختر التخصصات...", select_options,
                                              self.select_types, max_values=len(select_options)))
        children += [cards.sep(), cards.row(cards.secondary_btn("إلغاء", self.cancel)),
                     cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
        return children

    async def _confirm_children(self, notice: str | None = None) -> list:
        work_name = self.work["name"]
        currency = SETTINGS.get('currency', '$') or '$'
        estimated = 0.0
        for ch, t in zip(self.paid_chapters, self.types):
            estimated += await get_specialty_price(work_name, t)
        types_display = "، ".join(t.replace('_', ' ').title() for t in sorted(set(self.types)))
        chapters_display = "، ".join(f"فصل {c}" for c in self.paid_chapters[:12])
        if len(self.paid_chapters) > 12:
            chapters_display += f" و{len(self.paid_chapters) - 12} أخرى"
        children = [
            cards.header(["## تأكيد التسجيل", f"**{work_name}**"],
                         _member_avatar(self.member)),
            cards.sep(2),
            cards.text(
                f"**الفصول:** {len(self.paid_chapters)} فصل\n"
                f"**التفصيل:** {chapters_display}\n"
                f"**التخصصات:** {types_display}\n"
                f"**💰 الإجمالي التقديري:** {currency}{estimated:,.2f}"
            ),
        ]
        if self.notes:
            children.append(cards.sep())
            children.append(cards.text(f"**الملاحظات:** {cards.clamp(self.notes, 300)}"))
        if notice:
            children.append(cards.sep())
            children.append(cards.text(notice))
        children += [
            cards.sep(),
            cards.row(
                cards.success_btn("تأكيد التسجيل", self.commit),
                cards.secondary_btn("إضافة ملاحظة", self.ask_notes),
                cards.secondary_btn("إلغاء", self.cancel),
            ),
            cards.sep(),
            cards.text("-# **الخطوة 4 من 4** — مراجعة أخيرة قبل الحفظ."),
            cards.sep(),
            cards.text(f"-# {cards.BOT_SIGNATURE}"),
        ]
        return children


# ═══════════════════════════════════════════════════════════════
# الأمر + مستمع الرسائل
# ═══════════════════════════════════════════════════════════════
@bot.command(name="تسجيل")
@commands.cooldown(1, 5, commands.BucketType.user)
async def register_prefix(ctx, *, text_input=None):
    if ctx.guild is None:
        await ctx.send("استخدم أمر التسجيل داخل السيرفر.")
        return
    key = (ctx.guild.id, ctx.author.id, ctx.channel.id)

    # إغلاق أي جلسة سابقة لنفس العضو بهدوء
    old = _sessions.pop(key, None)
    if old:
        old.cancel_timer()
        try:
            await old.message.edit(view=cards.muted_card(
                "بدأت جلسة جديدة",
                ["أُغلقت الجلسة السابقة وبدأت جلسة تسجيل جديدة."],
                avatar_url=_bot_avatar()))
        except Exception:
            pass

    session = WizardSession(ctx.author, ctx.guild.id, ctx.channel.id)
    children = await session._work_pick_children()
    sent = await ctx.send(view=cards.Card(cards.ACCENT_GOLD, *children))
    session.message = sent
    _sessions[key] = session
    session.arm_timeout()


@bot.listen("on_message")
async def _wizard_listener(message: discord.Message):
    """استلام مدخلات الجلسة (الفصول أو الملاحظة) — لا يلمس أي رسالة أخرى."""
    if message.author.bot or not message.guild:
        return
    if message.content.startswith("!"):
        return
    key = (message.guild.id, message.author.id, message.channel.id)
    session = _sessions.get(key)
    if session is None:
        return
    if datetime.now() > session.expires:
        _sessions.pop(key, None)
        return
    session.touch()

    if session.step == "chapters":
        chapters = parse_chapter_range(message.content)
        if not chapters:
            await session.message.edit(view=cards.error_card(
                "نطاق غير مفهوم",
                ["لم أفهم صيغة الفصول — اكتب مثل `5` أو `1-5` أو `1,3,7`.",
                 "الجلسة ما زالت مستمرة، أعد الإرسال بصيغة صحيحة."],
                avatar_url=_bot_avatar()))
            return
        paid, free = filter_paid_chapters(session.work, chapters)
        if not paid:
            await session.message.edit(view=cards.error_card(
                "جميع الفصول مجانية",
                ["كل الفصول المدخلة مجانية ولم تُسجل.",
                 "الجلسة مستمرة — أرسل نطاقًا يحتوي فصولًا مدفوعة."],
                avatar_url=_bot_avatar()))
            return
        # ── بوابة أزورا: الفصل المنشور فقط (للأعمال المرتبطة) ──
        if get_azora_link(session.work):
            missing = await unpublished_chapters(session.work, paid)
            if missing:
                shown = "، ".join(f"فصل {m}" for m in missing[:10])
                await session.message.edit(view=cards.error_card(
                    "الفصل لم يُنشر بعد على أزورا",
                    [f"هذه الفصول غير موجودة بعد على صفحة العمل في أزورا: **{shown}**.",
                     "التسجيل عليها يُفتح تلقائيًا فور رفعها — تابع قناة الإعلانات.",
                     "الجلسة مستمرة — أرسل نطاقًا يحتوي فصولًا منشورة فقط."],
                    avatar_url=_bot_avatar()))
                return
        session.chapters_list = chapters
        session.paid_chapters = paid
        session.free_count = free
        session.types = []
        session.step = "types"
        await session.message.edit(view=cards.Card(cards.ACCENT_GOLD, *await session._types_children()))
        try:
            await message.delete()
        except Exception:
            pass
        return

    if session.step == "notes":
        text = message.content.strip()
        session.notes = None if text in ("تخطي", "لا", "-") else text[:300]
        session.step = "confirm"
        await session.message.edit(view=cards.Card(cards.ACCENT_GOLD, *await session._confirm_children()))
        try:
            await message.delete()
        except Exception:
            pass
        return
