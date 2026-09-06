"""إدارة الأشهر — نظام شهور حقيقي ومستدام:
- كل شهر له مفتاح (YYYY-MM) واسم حر، وسجلاته مستقلة تمامًا.
- الأعمال والأعضاء تبقى كما هي عبر الشهور — التبديل لا يحذف ولا يعيد تعيين أي شيء.
- /الشهور: عرض الشهور، الانتقال بينها، إنشاء شهر جديد، إعادة تسمية، حذف شهر.
"""
import asyncio
from datetime import datetime, timedelta
import discord
from discord import app_commands, ui
from state import bot
from helpers.core import (
    SETTINGS, is_admin, log_unauthorized, log_audit, save_settings,
    load_records, save_records, load_visible_records, update_stats,
    month_key_of, month_key_from_datetime, get_active_month_key,
    get_month_doc, get_month_name, ensure_month_doc, all_known_month_keys,
    remove_month_entries, DatabaseUnavailableError, load_works,
    get_isolated_work_names,
)
from ui import cards

MONTH_SELECT_EMOJI = "🗓️"   # إيموجي القوائم المنسدلة فقط

# جلسات إعادة التسمية في انتظار رسالة الاسم: key=(guild_id, user_id, channel_id)
_rename_pending: dict = {}


def _bot_avatar() -> str | None:
    return bot.user.display_avatar.url if bot.user else None


async def _month_line(month_key: str) -> str:
    """سطر تعريفي لشهر: الاسم + المفتاح + عدد الفصول."""
    records = await load_records()
    chapters = sum(1 for entries in records.values() for e in entries if month_key_of(e) == month_key)
    name = await get_month_name(month_key)
    return f"• **{name}**\n  -# `{month_key}` • {chapters} فصل"


def _next_month_key(after_key: str) -> str:
    """المفتاح التالي بعد شهر معين (تراكم شهري متسلسل)."""
    try:
        year, month = int(after_key[:4]), int(after_key[5:7])
    except (ValueError, TypeError):
        now = datetime.utcnow()
        return month_key_from_datetime(now)
    month += 1
    if month > 12:
        month = 1
        year += 1
    return f"{year:04d}-{month:02d}"


# ═══════════════════════════════════════════════════════════════
# لوحة إدارة الشهور
# ═══════════════════════════════════════════════════════════════
class MonthsHubView(ui.LayoutView):
    def __init__(self, guild: discord.Guild, user, notice: str | None = None, back=None):
        super().__init__(timeout=900.0)
        self.guild = guild
        self.user = user
        self.notice = notice
        self.back = back

    @classmethod
    async def create(cls, guild, user, notice=None, back=None):
        self = cls(guild, user, notice, back)
        await self.rebuild_async()
        return self

    async def _as_back(self):
        return await MonthsHubView.create(self.guild, self.user, back=self.back)

    async def rebuild_async(self):
        self.clear_items()
        children = await self.build_children()
        self.add_item(cards.container(cards.ACCENT_GOLD, *children))

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

    async def build_children(self) -> list:
        active_key = get_active_month_key()
        active_name = await get_month_name(active_key)
        month_records = await load_visible_records(active_key)
        month_chapters = sum(len(v) for v in month_records.values())
        month_net = sum(e.get("total", 0) for entries in month_records.values() for e in entries)
        currency = SETTINGS.get('currency', '$') or '$'
        works = await load_works()
        works_count = len([w for w in works if w.get("active", True)])

        keys = await all_known_month_keys()
        if active_key not in keys:
            keys.append(active_key)
            keys.sort()

        children: list = [
            cards.header(["## إدارة الشهور",
                          "كل شهر بسجلاته المستقلة — الأعمال والأعضاء تبقى كما هي عند التبديل."],
                         _bot_avatar()),
            cards.sep(2),
        ]
        if self.notice:
            children.append(cards.text(self.notice))
            children.append(cards.sep())

        # الشهر الحالي — كل معلومة في سطر مستقل
        active_doc = await get_month_doc(active_key)
        created_at = str(active_doc.get("created_at", ""))[:10] if active_doc else ""
        active_lines = [
            f"**الشهر الحالي:** {active_name}",
            f"**المفتاح:** `{active_key}`",
        ]
        if created_at:
            active_lines.append(f"**بدأ يُحتسب من:** {created_at}")
        active_lines += [
            f"**الفصول المسجلة:** {month_chapters}",
            f"**الأعضاء النشطون:** {len(month_records)}",
            f"**💰 صافي الشهر:** {currency}{month_net:,.2f}",
            f"**الأعمال المتاحة:** {works_count} عمل (ثابتة عبر كل الشهور)",
        ]
        children.append(cards.text("\n".join(active_lines)))
        children.append(cards.sep())

        # قائمة الشهور — سطر مستقل لكل شهر (حتى 8 ثم تُختصر)
        month_lines = []
        for i, key in enumerate(keys):
            if i >= 8:
                month_lines.append(f"-# … و{len(keys) - 8} شهرًا آخر في القائمة أدناه")
                break
            marker = " ← الحالي" if key == active_key else ""
            name = await get_month_name(key)
            month_lines.append(f"• **{name}** (`{key}`){marker}")
        children.append(cards.text("### كل الشهور\n" + "\n".join(month_lines)))

        # قائمة الانتقال بين الشهور
        options = []
        for key in keys[:25]:
            name = await get_month_name(key)
            recs = await load_visible_records(key)
            ch = sum(len(v) for v in recs.values())
            desc = f"{key} • {ch} فصل" + (" • الحالي" if key == active_key else "")
            options.append(discord.SelectOption(
                label=cards.clamp(name, 100), value=key,
                description=cards.clamp(desc, 100), emoji=MONTH_SELECT_EMOJI,
                default=False))
        if options:
            children.append(cards.sep())
            children.append(cards.text("-# للانتقال إلى شهر: اختره من القائمة — سجلاته تظهر فورًا وتُحفظ الجديدة فيه."))
            children.append(cards.make_select("الانتقال إلى شهر...", options, self._switch_selected))

        children.append(cards.sep())
        children.append(cards.row(
            cards.secondary_btn("إنشاء الشهر القادم", self._create_next),
            cards.secondary_btn("إعادة تسمية الحالي", self._rename_start),
            cards.secondary_btn("حذف شهر", self._open_delete),
        ))
        if self.back is not None:
            children.append(cards.sep())
            children.append(cards.row(cards.secondary_btn("عودة إلى لوحة التحكم", self._back_cb, emoji="↩")))
        children.append(cards.sep())
        children.append(cards.text(f"-# الأشهر متسلسلة والمسميات حرة • {cards.BOT_SIGNATURE}"))
        return children

    # ── الانتقال بين الشهور ──
    async def _switch_selected(self, interaction: discord.Interaction):
        if not is_admin(interaction):
            await interaction.response.send_message(view=cards.permission_card(_bot_avatar()), ephemeral=True)
            return
        key = interaction.data['values'][0]
        active_key = get_active_month_key()
        if key == active_key:
            await interaction.response.edit_message(
                view=await MonthsHubView.create(self.guild, self.user,
                                                notice="هذا هو الشهر النشط بالفعل.", back=self.back))
            return
        SETTINGS["active_month"] = key
        saved = await save_settings(SETTINGS)
        if not saved:
            await interaction.response.edit_message(view=cards.error_card(
                "تعذر تبديل الشهر", ["قاعدة البيانات غير متاحة — لم يُطبق التبديل."],
                avatar_url=_bot_avatar()))
            return
        await update_stats(key)
        await log_audit("تبديل_شهر", interaction.user.id, None, f"من {active_key} إلى {key}")
        name = await get_month_name(key)
        await interaction.response.edit_message(
            view=await MonthsHubView.create(
                self.guild, self.user,
                notice=f"**تم التبديل إلى {name}** (`{key}`)\nسجلاته تُعرض الآن، وكل تسجيل جديد سيُحفظ فيه.\nالأعمال والأعضاء لم تتأثر.",
                back=self.back))

    # ── إنشاء الشهر القادم ──
    async def _create_next(self, interaction: discord.Interaction):
        if not is_admin(interaction):
            await interaction.response.send_message(view=cards.permission_card(_bot_avatar()), ephemeral=True)
            return
        keys = await all_known_month_keys()
        latest = max(keys) if keys else month_key_from_datetime(datetime.utcnow())
        new_key = _next_month_key(latest)
        await ensure_month_doc(new_key, created_by=interaction.user.id)
        SETTINGS["active_month"] = new_key
        saved = await save_settings(SETTINGS)
        if not saved:
            await interaction.response.edit_message(view=cards.error_card(
                "تعذر إنشاء الشهر", ["قاعدة البيانات غير متاحة — لم يُحفظ الشهر الجديد."],
                avatar_url=_bot_avatar()))
            return
        await update_stats(new_key)
        await log_audit("انشاء_شهر", interaction.user.id, None, f"شهر جديد {new_key} وأصبح نشطًا")
        name = await get_month_name(new_key)
        await interaction.response.edit_message(
            view=await MonthsHubView.create(
                self.guild, self.user,
                notice=f"**تم إنشاء {name}** (`{new_key}`) والتبديل إليه.\nسجلاته تبدأ فارغة، والأعمال والأعضاء نفسهم ينتقلون معك.\nيمكنك تسميته من زر «إعادة تسمية الحالي».",
                back=self.back))

    # ── فتح قائمة حذف شهر ──
    async def _open_delete(self, interaction: discord.Interaction):
        if not is_admin(interaction):
            await interaction.response.send_message(view=cards.permission_card(_bot_avatar()), ephemeral=True)
            return
        view = await MonthDeleteSelectView.create(self.guild, self.user, back=self._as_back)
        await interaction.response.edit_message(view=view)

    # ── إعادة تسمية الشهر الحالي (بانتظار رسالة نصية) ──
    async def _rename_start(self, interaction: discord.Interaction):
        if not is_admin(interaction):
            await interaction.response.send_message(view=cards.permission_card(_bot_avatar()), ephemeral=True)
            return
        active_key = get_active_month_key()
        _rename_pending[(interaction.guild_id, interaction.user.id, interaction.channel_id)] = {
            "month_key": active_key,
            "expires": datetime.now() + timedelta(seconds=120),
        }

        async def _cancel(cb_interaction: discord.Interaction):
            _rename_pending.pop((interaction.guild_id, interaction.user.id, interaction.channel_id), None)
            await cb_interaction.response.edit_message(
                view=await MonthsHubView.create(self.guild, self.user, back=self.back))

        children = [
            cards.header(["## إعادة تسمية الشهر", f"**{await get_month_name(active_key)}** (`{active_key}`)"],
                         _bot_avatar()),
            cards.sep(2),
            cards.text("أرسل الاسم الجديد في هذه القناة الآن.\nلديك **دقيقتان** — أو اضغط إلغاء."),
            cards.sep(),
            cards.row(cards.secondary_btn("إلغاء", _cancel)),
            cards.sep(),
            cards.text(f"-# {cards.BOT_SIGNATURE}"),
        ]
        await interaction.response.edit_message(view=cards.Card(cards.ACCENT_GOLD, *children))


@bot.listen("on_message")
async def _rename_listener(message: discord.Message):
    """استلام اسم الشهر الجديد أثناء جلسة إعادة التسمية."""
    if message.author.bot or not message.guild:
        return
    key = (message.guild.id, message.author.id, message.channel.id)
    session = _rename_pending.get(key)
    if session is None:
        return
    if message.content.startswith("!"):
        return
    if datetime.now() > session["expires"]:
        _rename_pending.pop(key, None)
        try:
            await message.channel.send(view=cards.muted_card(
                "انتهت المهلة", ["انتهت دقيقتا إعادة التسمية — أعد المحاولة من /الشهور."],
                avatar_url=_bot_avatar()))
        except Exception:
            pass
        return

    new_name = message.content.strip()[:80]
    _rename_pending.pop(key, None)
    month_key = session["month_key"]
    try:
        await months_collection_update_name(month_key, new_name, message.author.id)
    except Exception as e:
        await message.channel.send(view=cards.error_card(
            "تعذرت إعادة التسمية", [f"`{str(e)[:200]}`"], avatar_url=_bot_avatar()))
        return
    await log_audit("اعادة_تسمية_شهر", message.author.id, None, f"{month_key} ← {new_name}")
    try:
        await message.delete()
    except Exception:
        pass
    active_name = await get_month_name(get_active_month_key())
    await message.channel.send(view=cards.success_card(
        "تمت إعادة تسمية الشهر",
        [f"الاسم الجديد: **{new_name}**\nالمفتاح: `{month_key}`",
         f"**الشهر الحالي:** {active_name}"],
        avatar_url=_bot_avatar()))


async def months_collection_update_name(month_key: str, name: str, user_id):
    from helpers.core import months_collection
    await months_collection.update_one(
        {"_id": month_key},
        {"$set": {"name": name, "renamed_by": str(user_id),
                  "renamed_at": datetime.utcnow().isoformat()}},
        upsert=True)


# ═══════════════════════════════════════════════════════════════
# حذف شهر — بطاقة تأكيد
# ═══════════════════════════════════════════════════════════════
class MonthDeleteSelectView(ui.LayoutView):
    """قائمة اختيار شهر للحذف (الحالي مستثنى دائمًا)."""

    def __init__(self, guild, user, back=None):
        super().__init__(timeout=600.0)
        self.guild = guild
        self.user = user
        self.back = back

    @classmethod
    async def create(cls, guild, user, back=None):
        self = cls(guild, user, back)
        return await self._build()

    async def _build(self):
        self.clear_items()
        active_key = get_active_month_key()
        keys = [k for k in await all_known_month_keys() if k != active_key]
        children: list = [
            cards.header(["## حذف شهر", "اختر الشهر المطلوب حذفه — الشهر الحالي غير مذكور عمدًا."],
                         _bot_avatar()),
            cards.sep(2),
        ]
        if not keys:
            children.append(cards.text("لا توجد شهور أخرى قابلة للحذف."))
        else:
            options = []
            for key in keys[:25]:
                name = await get_month_name(key)
                recs = await load_visible_records(key)
                ch = sum(len(v) for v in recs.values())
                options.append(discord.SelectOption(
                    label=cards.clamp(name, 100), value=key,
                    description=cards.clamp(f"{key} • {ch} فصل سيُحذف معه", 100),
                    emoji=MONTH_SELECT_EMOJI))
            children.append(cards.text("الحذف **نهائي**: يُحذف الشهر وسجلاته كلها. الأعمال والأعضاء لا تُمس."))
            children.append(cards.sep())
            children.append(cards.make_select("اختر الشهر للحذف...", options, self._picked))
        if self.back is not None:
            children += [cards.sep(), cards.row(
                cards.secondary_btn("عودة إلى إدارة الشهور", self._back_cb, emoji="↩"))]
        children += [cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
        self.add_item(cards.container(cards.ACCENT_GOLD, *children))
        return self

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

    async def _picked(self, interaction: discord.Interaction):
        key = interaction.data['values'][0]
        name = await get_month_name(key)
        recs = await load_visible_records(key)
        ch = sum(len(v) for v in recs.values())

        async def confirm(interaction2: discord.Interaction):
            removed = await remove_month_entries(key)
            from helpers.core import months_collection
            await months_collection.delete_one({"_id": key})
            await update_stats()
            await log_audit("حذف_شهر", interaction.user.id, None,
                            f"حذف {name} ({key}) مع {removed} سجل")
            parent = await MonthsHubView.create(
                self.guild, self.user,
                notice=f"**حُذف {name}** (`{key}`) نهائيًا مع **{removed}** سجل.\nالأعمال والأعضاء لم تتأثر.",
                back=self.back)
            await interaction2.response.edit_message(view=parent)

        children = [
            cards.header(["## تأكيد حذف الشهر", f"**{name}** (`{key}`)"], _bot_avatar()),
            cards.sep(2),
            cards.text(f"سيُحذف الشهر و**{ch} فصل** من سجلاته نهائيًا.\nلا يمكن التراجع."),
            cards.sep(),
            cards.row(
                cards.danger_btn("حذف الشهر نهائيًا", confirm),
                cards.secondary_btn("إلغاء", self._back_cb),
            ),
            cards.sep(),
            cards.text(f"-# {cards.BOT_SIGNATURE}"),
        ]
        await interaction.response.edit_message(view=cards.Card(cards.ACCENT_GOLD, *children))


@bot.tree.command(name="الشهور", description="إدارة شهور النظام: الانتقال والإنشاء والتسمية والحذف (للإدارة)")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def months_command(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message(view=cards.info_card(
            "داخل السيرفر فقط", ["هذا الأمر يعمل داخل السيرفر."], avatar_url=_bot_avatar()), ephemeral=True)
        return
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "الشهور")
        await interaction.response.send_message(view=cards.permission_card(_bot_avatar()), ephemeral=True)
        return
    view = await MonthsHubView.create(interaction.guild, interaction.user)
    await interaction.response.send_message(view=view)
