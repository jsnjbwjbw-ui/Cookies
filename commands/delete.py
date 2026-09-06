import discord
from discord.ext import commands
from discord import app_commands
from discord import ui
from state import bot
from helpers.core import *
from ui import cards


def _bot_avatar(interaction_or_bot):
    client = interaction_or_bot if hasattr(interaction_or_bot, "user") else interaction_or_bot
    user = getattr(client, "user", None)
    return user.display_avatar.url if user else None


def _member_avatar(member):
    try:
        return member.display_avatar.url if member else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# 🔧 بطاقة تأكيد قياسية — نفس قواعد أزرار بوت السحب:
#   تأكيد (Danger 4) + إلغاء (Secondary 2)، النتيجة ✅ خضراء
#   أو 🚫 رمادية بنفس صياغة «أُلغيت العملية».
# ═══════════════════════════════════════════════════════════════
async def send_confirm_card(
    interaction: discord.Interaction,
    title: str,
    detail: str,
    on_confirm,  # async (interaction2) -> None — يستدعى بعد الضغط على تأكيد
    *,
    confirm_label: str = "تأكيد",
    ephemeral: bool = True,
):
    avatar = _bot_avatar(interaction.client)

    async def confirm_action(interaction2: discord.Interaction):
        await on_confirm(interaction2)

    children: list = [
        cards.header([f"## {title}", f"<@{interaction.user.id}>"], avatar),
        cards.sep(2),
        cards.text(detail),
        cards.sep(),
        cards.row(
            cards.danger_btn(confirm_label, confirm_action),
            cards.secondary_btn("إلغاء", _cancel_action),
        ),
        cards.sep(),
        cards.text(f"-# {cards.BOT_SIGNATURE}"),
    ]
    await interaction.response.send_message(
        view=cards.Card(cards.ACCENT_GOLD, *children), ephemeral=ephemeral)


async def _cancel_action(interaction: discord.Interaction):
    await interaction.response.edit_message(view=cards.muted_card(
        "🚫 أُلغيت العملية",
        ["لم يُحذف أي شيء."],
        avatar_url=_bot_avatar(interaction.client)))


async def finish_card(interaction: discord.Interaction, title: str, lines: list, *, green: bool = True):
    card = (cards.success_card if green else cards.muted_card)(title, lines,
                                                               avatar_url=_bot_avatar(interaction.client))
    await interaction.response.edit_message(view=card)


# ═══════════════════════════════════════════════════════════════
# 🗑️ لوحة خيارات الحذف — قائمة منسدلة داخل حاوية ذهبية
# ═══════════════════════════════════════════════════════════════
class DeletePanel(ui.LayoutView):
    def __init__(self, moderator: discord.abc.User, member: discord.Member, work_name=None):
        super().__init__(timeout=120.0)
        self.moderator = moderator
        self.member = member
        self.work_name = work_name
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        options = []
        if self.work_name:
            options.append(discord.SelectOption(label="🗑️ حذف كل فصول هذا العمل", value="delete_work",
                                                description=cards.clamp(f"حذف كل فصول عمل {self.work_name}", 100)))
            options.append(discord.SelectOption(label="🔍 حذف فصل محدد", value="delete_chapter",
                                                description="اختيار فصل لحذفه"))
        else:
            options.append(discord.SelectOption(label="👤 حذف كل سجلات العضو", value="delete_all_user",
                                                description="حذف كل سجلات العضو بالكامل"))
        options.append(discord.SelectOption(label="❌ إلغاء", value="cancel", description="إغلاق اللوحة دون حذف"))
        label_line = (f"**{self.member.mention}** — عمل «{cards.clamp(self.work_name, 60)}»"
                      if self.work_name else f"**{self.member.mention}**")
        children: list = [
            cards.header(["## 🗑️ خيارات الحذف", label_line], _member_avatar(self.member)),
            cards.sep(2),
            cards.make_select("اختر إجراء...", options, self.select_callback),
            cards.sep(),
            cards.text(f"-# {cards.BOT_SIGNATURE}"),
        ]
        self.add_item(cards.container(cards.ACCENT_GOLD, *children))

    async def select_callback(self, interaction: discord.Interaction):
        value = interaction.data['values'][0]
        if value == "cancel":
            await interaction.response.edit_message(view=cards.muted_card(
                "🚫 أُلغيت العملية", ["لم يُحذف أي شيء."], avatar_url=_bot_avatar(interaction.client)))
            return

        if value == "delete_all_user":
            async def confirm(interaction2: discord.Interaction):
                records = await load_records()
                if str(self.member.id) in records:
                    del records[str(self.member.id)]
                    await save_records(records)
                    await log_audit("حذف_كل_سجلات_العضو", interaction.user.id, self.member.id, "حذف كل السجلات")
                    await update_stats()
                    await finish_card(interaction2, "✅ تم حذف كل سجلات العضو",
                                      [f"**العضو:** {self.member.mention}", "لم يتبقَّ أي سجل له."])
                else:
                    await finish_card(interaction2, "❌ لا توجد سجلات",
                                      [f"لا توجد سجلات للعضو {self.member.mention}."], green=False)
            await send_confirm_card(
                interaction, "⚠️ تأكيد حذف السجلات",
                f"هل أنت متأكد من حذف **كل** سجلات {self.member.mention}؟ لا يمكن التراجع.",
                confirm)
            return

        if value == "delete_work" and self.work_name:
            async def confirm(interaction2: discord.Interaction):
                records = await load_records()
                user_id_str = str(self.member.id)
                if user_id_str in records:
                    new_entries = [e for e in records[user_id_str] if e.get("work_name") != self.work_name]
                    removed_count = len(records[user_id_str]) - len(new_entries)
                    records[user_id_str] = new_entries
                    if not records[user_id_str]:
                        del records[user_id_str]
                    await save_records(records)
                    await log_audit("حذف_عمل_كامل", interaction.user.id, self.member.id,
                                    f"حذف عمل {self.work_name} ({removed_count} فصل)")
                    await update_stats()
                    await finish_card(interaction2, "✅ تم حذف العمل",
                                      [f"حُذف عمل «{self.work_name}» بالكامل — **{removed_count}** فصل.",
                                       f"**العضو:** {self.member.mention}"])
                else:
                    await finish_card(interaction2, "❌ لا توجد سجلات",
                                      [f"لا توجد سجلات للعضو {self.member.mention}."], green=False)
            await send_confirm_card(
                interaction, "⚠️ تأكيد حذف العمل",
                f"هل أنت متأكد من حذف كل فصول عمل «{self.work_name}» للعضو {self.member.mention}؟",
                confirm)
            return

        if value == "delete_chapter":
            records = await load_records()
            user_id_str = str(self.member.id)
            if user_id_str not in records:
                await interaction.response.send_message(
                    view=cards.error_card("❌ لا توجد سجلات", [f"لا توجد سجلات للعضو {self.member.mention}."]),
                    ephemeral=True)
                return
            work_entries = [e for e in records[user_id_str] if e.get("work_name") == self.work_name]
            if not work_entries:
                await interaction.response.send_message(
                    view=cards.error_card("❌ لا توجد فصول", ["لا توجد فصول لهذا العمل."]),
                    ephemeral=True)
                return
            options = []
            seen_chapters = set()
            for e in work_entries:
                ch = e.get('chapter')
                if ch not in seen_chapters:
                    seen_chapters.add(ch)
                    options.append(discord.SelectOption(label=f"فصل {ch}", value=str(ch),
                                                        description=f"التخصص: {e.get('work_type')}"))
            options.append(discord.SelectOption(label="❌ إلغاء", value="cancel"))
            view = ChapterDeletePanel(self.moderator, self.member, self.work_name, options)
            await interaction.response.edit_message(view=view)


class ChapterDeletePanel(ui.LayoutView):
    def __init__(self, moderator, member, work_name, options):
        super().__init__(timeout=120.0)
        self.moderator = moderator
        self.member = member
        self.work_name = work_name
        self.options = options
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        children: list = [
            cards.header(["## 🔍 حذف فصل محدد",
                          f"**{self.member.mention}** — عمل «{cards.clamp(self.work_name, 60)}»"], _member_avatar(self.member)),
            cards.sep(2),
            cards.make_select("اختر الفصل المراد حذفه...", self.options, self.select_callback),
            cards.sep(),
            cards.text(f"-# {cards.BOT_SIGNATURE}"),
        ]
        self.add_item(cards.container(cards.ACCENT_GOLD, *children))

    async def select_callback(self, interaction: discord.Interaction):
        chapter = interaction.data['values'][0]
        if chapter == "cancel":
            await interaction.response.edit_message(view=cards.muted_card(
                "🚫 أُلغيت العملية", ["لم يُحذف أي شيء."], avatar_url=_bot_avatar(interaction.client)))
            return

        async def confirm(interaction2: discord.Interaction):
            records2 = await load_records()
            user_id_str = str(self.member.id)
            if user_id_str in records2:
                new_entries = [e for e in records2[user_id_str]
                               if not (e.get("work_name") == self.work_name and str(e.get("chapter")) == chapter)]
                removed = len(records2[user_id_str]) - len(new_entries)
                records2[user_id_str] = new_entries
                if not records2[user_id_str]:
                    del records2[user_id_str]
                await save_records(records2)
                await log_audit("حذف_فصل", interaction.user.id, self.member.id,
                                f"حذف فصل {chapter} من عمل {self.work_name}")
                await update_stats()
                await finish_card(interaction2, "✅ تم حذف الفصل",
                                  [f"حُذف **فصل {chapter}** من عمل «{self.work_name}».",
                                   f"**العضو:** {self.member.mention}"])
            else:
                await finish_card(interaction2, "❌ لا توجد سجلات",
                                  [f"لا توجد سجلات للعضو {self.member.mention}."], green=False)
        await send_confirm_card(
            interaction, "⚠️ تأكيد حذف الفصل",
            f"هل أنت متأكد من حذف **فصل {chapter}** من عمل «{self.work_name}»؟",
            confirm)


# ═══════════════════════════════════════════════════════════════
# /حذف — الأمر الرئيسي
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="حذف", description="حذف سجلات العضو - للمشرفين")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def delete_advanced(interaction: discord.Interaction, member: discord.Member, work_name: str = None):
    avatar = _bot_avatar(interaction.client)
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "حذف")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    if not channel_allowed(interaction):
        await interaction.response.send_message(view=cards.channel_card(SETTINGS.get("allowed_channels", []), avatar), ephemeral=True)
        return
    records = await load_records()
    user_id_str = str(member.id)
    if user_id_str not in records or not records[user_id_str]:
        await interaction.response.send_message(view=cards.error_card(
            "❌ لا توجد سجلات", [f"العضو {member.mention} ما عنده أي شغل محفوظ."],
            avatar_url=_member_avatar(member)), ephemeral=True)
        return
    if work_name:
        work_exists = any(e.get("work_name") == work_name for e in records[user_id_str])
        if not work_exists:
            await interaction.response.send_message(view=cards.error_card(
                "❌ العمل غير موجود", [f"لا يوجد عمل باسم `{work_name}` لهذا العضو."]), ephemeral=True)
            return
        await interaction.response.send_message(view=DeletePanel(interaction.user, member, work_name))
    else:
        works = sorted({e.get("work_name") for e in records[user_id_str]})
        options = [discord.SelectOption(label=f"📖 {cards.clamp(w, 90)}", value=w) for w in works[:24]]
        options.append(discord.SelectOption(label="👤 حذف كل سجلات العضو", value="delete_all_user"))
        options.append(discord.SelectOption(label="❌ إلغاء", value="cancel"))
        view = WorkPickPanel(interaction.user, member, options, works)
        await interaction.response.send_message(view=view)


class WorkPickPanel(ui.LayoutView):
    def __init__(self, moderator, member, options, works):
        super().__init__(timeout=120.0)
        self.moderator = moderator
        self.member = member
        self.works = works
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        children: list = [
            cards.header(["## 🗑️ اختر العمل أو الإجراء", f"**{self.member.mention}**"], _member_avatar(self.member)),
            cards.sep(2),
            cards.make_select("اختر عملاً أو خياراً...", self._options(), self.select_callback),
            cards.sep(),
            cards.text(f"-# {cards.BOT_SIGNATURE}"),
        ]
        self.add_item(cards.container(cards.ACCENT_GOLD, *children))

    def _options(self):
        options = [discord.SelectOption(label=f"📖 {cards.clamp(w, 90)}", value=w) for w in self.works[:24]]
        options.append(discord.SelectOption(label="👤 حذف كل سجلات العضو", value="delete_all_user"))
        options.append(discord.SelectOption(label="❌ إلغاء", value="cancel"))
        return options

    async def select_callback(self, interaction: discord.Interaction):
        value = interaction.data['values'][0]
        if value == "cancel":
            await interaction.response.edit_message(view=cards.muted_card(
                "🚫 أُلغيت العملية", ["لم يُحذف أي شيء."], avatar_url=_bot_avatar(interaction.client)))
            return
        if value == "delete_all_user":
            async def confirm(interaction2: discord.Interaction):
                records2 = await load_records()
                if str(self.member.id) in records2:
                    del records2[str(self.member.id)]
                    await save_records(records2)
                    await log_audit("حذف_كل_سجلات_العضو", interaction.user.id, self.member.id, "حذف كل السجلات")
                    await update_stats()
                    await finish_card(interaction2, "✅ تم حذف كل سجلات العضو",
                                      [f"**العضو:** {self.member.mention}", "لم يتبقَّ أي سجل له."])
                else:
                    await finish_card(interaction2, "❌ لا توجد سجلات",
                                      [f"لا توجد سجلات للعضو {self.member.mention}."], green=False)
            await send_confirm_card(
                interaction, "⚠️ تأكيد حذف السجلات",
                f"هل أنت متأكد من حذف **كل** سجلات {self.member.mention}؟ لا يمكن التراجع.",
                confirm)
            return
        work = value
        await interaction.response.edit_message(view=DeletePanel(interaction.user, self.member, work))


@bot.command(name="حذف")
@commands.has_permissions(manage_messages=True)
@commands.cooldown(1, 5, commands.BucketType.user)
async def delete_work_text(ctx, member: discord.Member = None, number: int = None):
    if member is None or number is None:
        await ctx.send("**الاستخدام:** `!حذف @member 2`\nأو استخدم الأمر `/حذف` للخيارات المتقدمة.")
        return
    records = await load_records()
    user_id = str(member.id)
    if user_id not in records or not records[user_id]:
        await ctx.send("❌ هذا العضو ما عنده أي شغل محفوظ.")
        return
    if number < 1 or number > len(records[user_id]):
        await ctx.send("❌ رقم السجل غير صحيح.")
        return
    deleted = records[user_id].pop(number - 1)
    if not records[user_id]:
        del records[user_id]
    await save_records(records)
    await log_audit("حذف سجل (نصي)", ctx.author.id, member.id, f"السجل #{number}: {deleted.get('work_name')} - فصل {deleted.get('chapter')}")
    await update_stats()
    avatar = ctx.bot.user.display_avatar.url if ctx.bot.user else None
    currency = SETTINGS.get('currency', '$') or '$'
    children: list = [
        cards.header(["## 🗑️ تم حذف السجل", f"**{member.mention}**"], avatar),
        cards.sep(2),
        cards.text(
            f"**📖 العمل:** {deleted.get('work_name', 'غير محدد')}\n"
            f"**📑 الفصل:** {deleted.get('chapter', 'غير محدد')}\n"
            f"**🛠️ التخصص:** {deleted.get('work_type', 'غير محدد')}\n"
            f"**💰 المبلغ:** {currency}{deleted.get('total', 0):.2f}"
        ),
        cards.sep(),
        cards.text(f"-# {cards.BOT_SIGNATURE}"),
    ]
    await ctx.send(view=cards.Card(cards.ACCENT_RED, *children))


# ═══════════════════════════════════════════════════════════════
# /حذف_الكل — يستثني الأعمال المعزولة (قائمة مراحل ✓ في النتيجة)
# ═══════════════════════════════════════════════════════════════
async def _delete_all_core(responder, user: discord.abc.User, avatar):
    records = await load_records()
    works = await load_works()
    isolated_names = get_isolated_work_names(works)

    total_removed = 0
    preserved_isolated = 0
    for user_id in list(records.keys()):
        new_entries = [e for e in records[user_id] if e.get("work_name") in isolated_names]
        removed = len(records[user_id]) - len(new_entries)
        total_removed += removed
        preserved_isolated += len(new_entries)
        if new_entries:
            records[user_id] = new_entries
        else:
            del records[user_id]

    if total_removed == 0:
        await responder(cards.error_card(
            "📭 لا يوجد ما يُحذف",
            ["لا توجد سجلات قابلة للحذف (جميعها معزولة أو لا سجلات)."], avatar_url=avatar))
        return

    await save_records(records)
    await log_audit("حذف_الكل", user.id, None, f"{total_removed} سجل (استثناء المعزولة: {preserved_isolated})")
    await update_stats()

    checklist = [f"✓ حذف السجلات — {total_removed} سجل"]
    if preserved_isolated > 0:
        checklist.append(f"⊘ سجلات الأعمال المعزولة — {preserved_isolated} سجل (مُستثناة)")
    children = [
        cards.header(["## ✅ تم حذف السجلات", f"<@{user.id}>"], avatar),
        cards.sep(2),
        cards.text("\n".join(checklist)),
        cards.sep(),
        cards.text(f"-# {cards.BOT_SIGNATURE}"),
    ]
    await responder(cards.Card(cards.ACCENT_GREEN, *children))


@bot.tree.command(name="حذف_الكل", description="حذف كل السجلات - للمشرفين (يستثني الأعمال المعزولة)")
@app_commands.checks.cooldown(1, 10, key=lambda i: (i.user.id, i.command.qualified_name))
async def delete_all_work_slash(interaction: discord.Interaction):
    avatar = _bot_avatar(interaction.client)
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "حذف_الكل")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    if not channel_allowed(interaction):
        await interaction.response.send_message(view=cards.channel_card(SETTINGS.get("allowed_channels", []), avatar), ephemeral=True)
        return

    async def confirm(interaction2: discord.Interaction):
        async def responder(card):
            await interaction2.response.edit_message(view=card)
        await _delete_all_core(responder, interaction.user, avatar)

    await send_confirm_card(
        interaction, "⚠️ تأكيد حذف السجلات",
        "سيتم حذف **كل السجلات** غير المعزولة من كل الأعضاء. لا يمكن التراجع.",
        confirm)


@bot.command(name="حذف_الكل")
@commands.has_permissions(manage_messages=True)
@commands.cooldown(1, 10, commands.BucketType.user)
async def delete_all_work_text(ctx):
    avatar = ctx.bot.user.display_avatar.url if ctx.bot.user else None

    async def responder(card):
        await ctx.send(view=card)
    await _delete_all_core(responder, ctx.author, avatar)


# ═══════════════════════════════════════════════════════════════
# /حذف_كل_الأعمال
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="حذف_كل_الأعمال", description="حذف جميع الأعمال من القائمة (للمشرفين فقط)")
@app_commands.checks.cooldown(1, 10, key=lambda i: (i.user.id, i.command.qualified_name))
async def delete_all_works(interaction: discord.Interaction):
    avatar = _bot_avatar(interaction.client)
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "حذف_كل_الأعمال")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    works = await load_works()
    if not works:
        await interaction.response.send_message(view=cards.error_card(
            "📭 لا توجد أعمال", ["لا توجد أعمال في القائمة."]), ephemeral=True)
        return

    async def confirm(interaction2: discord.Interaction):
        await save_works([])
        await log_audit("حذف_كل_الأعمال", interaction.user.id, None, f"تم حذف {len(works)} عمل")
        await finish_card(interaction2, "✅ تم حذف جميع الأعمال",
                          [f"حُذفت **{len(works)}** أعمال من القائمة.", "لم تتأثر السجلات المالية."])

    await send_confirm_card(
        interaction, "⚠️ تأكيد حذف الأعمال",
        f"سيتم حذف **جميع الأعمال ({len(works)} عمل)** من القائمة.\nلن تتأثر السجلات.",
        confirm)
