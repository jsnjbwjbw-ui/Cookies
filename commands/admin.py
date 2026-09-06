from datetime import datetime
import json
import pandas as pd
from io import BytesIO
import discord
from discord import app_commands
from discord import ui
from state import bot
from helpers.core import *
from tasks.lifecycle import work_autocomplete, specialty_autocomplete
from ui import cards


def _bot_avatar():
    return bot.user.display_avatar.url if bot.user else None


# ═══════════════════════════════════════════════════════════════
# /تصدير — تصدير JSON (للعضو المخصص فقط)
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="تصدير", description="تصدير كل البيانات إلى JSON (للعضو المخصص فقط)")
@app_commands.checks.cooldown(1, 10, key=lambda i: (i.user.id, i.command.qualified_name))
async def export_excel(interaction: discord.Interaction):
    # السماح فقط لعضو واحد محدد بمعرفه
    if interaction.user.id != 656783724662226963:
        await interaction.response.send_message(view=cards.permission_card(_bot_avatar()), ephemeral=True)
        return

    records = await load_records()
    data = json.dumps(records, ensure_ascii=False, indent=2)
    buffer = BytesIO(data.encode('utf-8'))
    buffer.seek(0)
    await interaction.response.send_message(
        file=discord.File(buffer, filename=f"backup_{datetime.utcnow().date()}.json")
    )


# ═══════════════════════════════════════════════════════════════
# /اعدادات — مركز الإعدادات بنمط بطاقة «إعدادات هذا السيرفر» في ZEUS
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="اعدادات", description="إعدادات هذا السيرفر - العملة والقنوات وموعد الدفع")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def bot_settings(interaction: discord.Interaction, العملة: str = None, قناة_الإشعارات: discord.TextChannel = None, حد_التنبيه: float = None):
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "اعدادات")
        await interaction.response.send_message(view=cards.permission_card(_bot_avatar()), ephemeral=True)
        return

    avatar = _bot_avatar()
    currency = SETTINGS.get('currency', '$') or '$'
    changed_lines = []

    if العملة or قناة_الإشعارات or حد_التنبيه is not None:
        if العملة:
            SETTINGS["currency"] = العملة
            changed_lines.append(f"✓ العملة ← {العملة}")
        if قناة_الإشعارات:
            SETTINGS["notify_channel_id"] = قناة_الإشعارات.id
            changed_lines.append(f"✓ قناة الإشعارات ← <#{قناة_الإشعارات.id}>")
        if حد_التنبيه is not None:
            SETTINGS["alert_threshold"] = حد_التنبيه
            changed_lines.append(f"✓ حد التنبيه ← {currency}{حد_التنبيه:.2f}")
        await save_settings(SETTINGS)
        currency = SETTINGS.get('currency', '$') or '$'

    notify_channel = SETTINGS.get('notify_channel_id')
    backup_channel = SETTINGS.get('daily_backup_channel_id')
    payment_day = SETTINGS.get("payment_day")
    channels = SETTINGS.get("allowed_channels", [])
    channels_str = "، ".join(f"<#{ch}>" if isinstance(ch, int) else f"#{ch}" for ch in channels) or "غير محددة"

    children: list = [
        cards.header(["## ⚙️ إعدادات هذا السيرفر", f"سيرفر **{interaction.guild.name}**"], avatar),
        cards.sep(2),
    ]
    if changed_lines:
        children.append(cards.text("**التغييرات المطبقة**\n" + "\n".join(changed_lines)))
        children.append(cards.sep())
    children.append(cards.text(
        "**ما هو مطبق الآن في هذا السيرفر:**\n"
        f"**1. 💰 المال** — العملة: **{currency}** — حد التنبيه: **{currency}{SETTINGS.get('alert_threshold', 10):.2f}**\n"
        f"**2. 🔔 القنوات** — الإشعارات: " +
        (f"**<#{notify_channel}>**" if notify_channel else "**غير محدد**") +
        " — النسخ الاحتياطي: " +
        (f"**<#{backup_channel}>**" if backup_channel else "**غير محدد**") +
        f"\n**3. 📢 قنوات التسجيل** — {channels_str}\n"
        f"**4. 📅 موعد الدفع** — " +
        (f"**يوم {payment_day} الساعة {SETTINGS.get('payment_hour', 0)}:00**" if payment_day else "**غير محدد**")
    ))
    children.append(cards.sep())
    children.append(cards.text(
        "-# للتعديل: /اعدادات مع الخيارات (العملة/قناة_الإشعارات/حد_التنبيه) • /تحديد_قنوات للقنوات المسموحة • /تحديد_موعد_الدفع للموعد الشهري."
    ))
    children.append(cards.sep())
    children.append(cards.text(f"-# {cards.BOT_SIGNATURE}"))
    await interaction.response.send_message(view=cards.Card(
        cards.ACCENT_GREEN if changed_lines else cards.ACCENT_GOLD, *children), ephemeral=True)


# ═══════════════════════════════════════════════════════════════
# إدارة الأعمال
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="اضافة_عمل", description="إضافة عمل جديد إلى قائمة الأعمال المدفوعة (للمشرفين)")
@app_commands.describe(الاسم="اسم العمل", بداية_الفصول_المدفوعة="أول فصل مدفوع (اختياري، اتركه فارغاً إذا كان العمل كله مدفوع)", نشط="هل العمل نشط الآن؟")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def add_work(interaction: discord.Interaction, الاسم: str, بداية_الفصول_المدفوعة: int = None, نشط: bool = True):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "اضافة_عمل")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    works = await load_works()
    if any(w["name"] == الاسم for w in works):
        await interaction.response.send_message(view=cards.error_card(
            "❌ العمل موجود بالفعل", [f"العمل `{الاسم}` موجود مسبقًا في القائمة."], avatar_url=avatar), ephemeral=True)
        return
    new_work = {"name": الاسم, "paid_start": بداية_الفصول_المدفوعة, "active": نشط}
    works.append(new_work)
    await save_works(works)
    await log_audit("اضافة_عمل", interaction.user.id, None, f"أضاف عمل {الاسم} (paid_start={بداية_الفصول_المدفوعة}, active={نشط})")
    desc = "كل الفصول مدفوعة" if بداية_الفصول_المدفوعة is None else f"يبدأ الدفع من فصل {بداية_الفصول_المدفوعة}"
    checklist = [
        f"✓ إضافة العمل — «{الاسم}»",
        f"✓ سياسة الدفع — {desc}",
        f"{'✓ الحالة — نشط' if نشط else '⊘ الحالة — معطل'}",
    ]
    children = [
        cards.header(["## ✅ تمت إضافة العمل", f"<@{interaction.user.id}>"], avatar),
        cards.sep(2),
        cards.text("\n".join(checklist)),
        cards.sep(),
        cards.text(f"-# {cards.BOT_SIGNATURE}"),
    ]
    await interaction.response.send_message(view=cards.Card(cards.ACCENT_GREEN, *children), ephemeral=True)


@bot.tree.command(name="حذف_عمل", description="حذف عمل من القائمة (للمشرفين)")
@app_commands.autocomplete(العمل=work_autocomplete)
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def delete_work(interaction: discord.Interaction, العمل: str):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "حذف_عمل")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    works = await load_works()
    target = next((w for w in works if w["name"] == العمل), None)
    if not target:
        await interaction.response.send_message(view=cards.error_card(
            "❌ العمل غير موجود", [f"العمل `{العمل}` غير موجود في القائمة."], avatar_url=avatar), ephemeral=True)
        return

    async def delete_with_records(interaction2: discord.Interaction):
        async def confirm(interaction3: discord.Interaction):
            removed = await delete_all_records_of_work(العمل)
            new_works = [w for w in works if w["name"] != العمل]
            await save_works(new_works)
            await log_audit("حذف_عمل_مع_السجلات", interaction2.user.id, None, f"حذف {العمل} و {removed} سجل")
            await _finish(interaction3, "✅ تم حذف العمل وسجلاته",
                          [f"حُذف عمل «{العمل}» مع كل سجلاته.", f"**السجلات المحذوفة:** {removed}"])
        await _confirm_card(interaction2, "⚠️ تأكيد نهائي",
                            f"سيتم حذف العمل «{العمل}» **وكل سجلاته** نهائيًا.", confirm)

    async def delete_work_only(interaction2: discord.Interaction):
        async def confirm(interaction3: discord.Interaction):
            new_works = [w for w in works if w["name"] != العمل]
            await save_works(new_works)
            await log_audit("حذف_عمل_فقط", interaction2.user.id, None, f"حذف {العمل} من القائمة (السجلات باقية)")
            await _finish(interaction3, "✅ تم حذف العمل من القائمة",
                          [f"حُذف عمل «{العمل}» من القائمة.", "السجلات لم تُمس."])
        await _confirm_card(interaction2, "⚠️ تأكيد",
                            f"سيتم حذف العمل «{العمل}» من القائمة فقط (السجلات تبقى).", confirm)

    children: list = [
        cards.header(["## 🗑️ حذف العمل", f"**«{العمل}»** — اختر الطريقة:"], avatar),
        cards.sep(2),
        cards.row(
            cards.danger_btn("حذف العمل وكل سجلاته", delete_with_records),
            cards.make_button("حذف العمل فقط (إخفاؤه)", style=discord.ButtonStyle.primary, callback=delete_work_only),
            cards.secondary_btn("إلغاء", _cancel_to_muted),
        ),
        cards.sep(),
        cards.text(f"-# {cards.BOT_SIGNATURE}"),
    ]
    await interaction.response.send_message(view=cards.Card(cards.ACCENT_GOLD, *children), ephemeral=True)


async def _cancel_to_muted(interaction: discord.Interaction):
    await interaction.response.edit_message(view=cards.muted_card(
        "🚫 أُلغيت العملية", ["لم يُحذف أي شيء."], avatar_url=_bot_avatar()))


async def _confirm_card(interaction: discord.Interaction, title: str, detail: str, on_confirm):
    avatar = _bot_avatar()
    children: list = [
        cards.header([f"## {title}", f"<@{interaction.user.id}>"], avatar),
        cards.sep(2),
        cards.text(detail),
        cards.sep(),
        cards.row(
            cards.danger_btn("تأكيد", on_confirm),
            cards.secondary_btn("إلغاء", _cancel_to_muted),
        ),
        cards.sep(),
        cards.text(f"-# {cards.BOT_SIGNATURE}"),
    ]
    await interaction.response.send_message(view=cards.Card(cards.ACCENT_GOLD, *children), ephemeral=True)


async def _finish(interaction: discord.Interaction, title: str, lines: list, *, gray: bool = False):
    card = (cards.muted_card if gray else cards.success_card)(title, lines, avatar_url=_bot_avatar())
    await interaction.response.edit_message(view=card)


@bot.tree.command(name="تعديل_عمل", description="تعديل بيانات عمل (للمشرفين)")
@app_commands.autocomplete(العمل=work_autocomplete)
@app_commands.describe(العمل="اختر العمل", الاسم_الجديد="اسم جديد (اختياري)", بداية_الفصول_المدفوعة="أول فصل مدفوع (اتركه فارغاً إن لم يتغير)", الكل_مدفوع="تفعيل إذا كان العمل كله مدفوعاً", نشط="حالة النشاط")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def edit_work(interaction: discord.Interaction, العمل: str, الاسم_الجديد: str = None, بداية_الفصول_المدفوعة: int = None, الكل_مدفوع: bool = False, نشط: bool = None):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "تعديل_عمل")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    works = await load_works()
    target = next((w for w in works if w["name"] == العمل), None)
    if not target:
        await interaction.response.send_message(view=cards.error_card(
            "❌ العمل غير موجود", [f"العمل `{العمل}` غير موجود في القائمة."], avatar_url=avatar), ephemeral=True)
        return
    changed = []
    if الاسم_الجديد and الاسم_الجديد != target["name"]:
        if any(w["name"] == الاسم_الجديد for w in works):
            await interaction.response.send_message(view=cards.error_card(
                "❌ الاسم موجود مسبقاً", [f"الاسم `{الاسم_الجديد}` مستخدم بالفعل."], avatar_url=avatar), ephemeral=True)
            return
        target["name"] = الاسم_الجديد
        changed.append(f"الاسم ← {الاسم_الجديد}")
    if الكل_مدفوع:
        target["paid_start"] = None
        changed.append("كل الفصول مدفوعة")
    elif بداية_الفصول_المدفوعة is not None:
        target["paid_start"] = بداية_الفصول_المدفوعة
        changed.append(f"بداية الدفع ← فصل {بداية_الفصول_المدفوعة}")
    if نشط is not None and نشط != target.get("active", True):
        target["active"] = نشط
        changed.append(f"نشط ← {نشط}")
    if not changed:
        await interaction.response.send_message(view=cards.info_card(
            "ℹ️ لا تغييرات", ["لم تقم بأي تغيير."], avatar_url=avatar), ephemeral=True)
        return
    await save_works(works)
    await log_audit("تعديل_عمل", interaction.user.id, None, f"تعديل {العمل}: {', '.join(changed)}")
    checklist = "\n".join(f"✓ {c}" for c in changed)
    await interaction.response.send_message(view=cards.success_card(
        "✅ تم تعديل العمل", [f"**«{العمل}»**\n{checklist}"], avatar_url=avatar), ephemeral=True)


class WorksListPaginator(ui.LayoutView):
    def __init__(self, works: list):
        super().__init__(timeout=300.0)
        self.works = works
        self.currency = SETTINGS.get('currency', '$') or '$'
        self.current_page = 0
        self.per_page = 20
        self.total_pages = max(1, (len(works) + self.per_page - 1) // self.per_page)
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        avatar = _bot_avatar()
        children: list = [
            cards.header(["## 📋 قائمة الأعمال المدفوعة", f"**{len(self.works)}** عمل في القائمة."], avatar),
            cards.sep(2),
        ]
        start = self.current_page * self.per_page
        page_works = self.works[start:start + self.per_page]
        blocks = []
        for w in page_works:
            paid_info = "كل الفصول مدفوعة" if w.get("paid_start") is None else f"يبدأ الدفع من فصل {w['paid_start']}"
            active_icon = "✅" if w.get("active", True) else "❌"
            isolated_info = "\n⏸️ معزول عن الحسابات الظاهرة" if is_work_isolated(w) else ""
            blocks.append(f"• {active_icon} **{w['name']}** — {paid_info}{isolated_info}")
        children.append(cards.text(cards.clamp("\n".join(blocks), 3400)))
        if self.total_pages > 1:
            children += [cards.sep(), cards.pager_row(self.current_page, self.total_pages,
                                                      self.previous_page, self.next_page)]
        children += [cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
        self.add_item(cards.Card(cards.ACCENT_GOLD, *children))

    async def refresh(self, interaction: discord.Interaction):
        self.rebuild()
        await interaction.response.edit_message(view=self)

    async def previous_page(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        await self.refresh(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        await self.refresh(interaction)


@bot.tree.command(name="عرض_الاعمال", description="عرض قائمة الأعمال المدفوعة وحالتها")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def list_works(interaction: discord.Interaction):
    works = await load_works()
    if not works:
        await interaction.response.send_message(view=cards.info_card(
            "📭 لا توجد أعمال", ["لا توجد أعمال في القائمة."], avatar_url=_bot_avatar()), ephemeral=True)
        return
    view = WorksListPaginator(works)
    await interaction.response.send_message(view=view)


@bot.tree.command(name="عزل_عمل", description="عزل عمل كامل عن عرض المستحقات دون حذف سجلاته")
@app_commands.autocomplete(العمل=work_autocomplete)
@app_commands.describe(العمل="اسم العمل المطلوب عزله", السبب="سبب اختياري يظهر في السجل الإداري")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def isolate_work(interaction: discord.Interaction, العمل: str, السبب: str = None):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "عزل_عمل")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    works = await load_works()
    target = next((w for w in works if w["name"] == العمل), None)
    if not target:
        await interaction.response.send_message(view=cards.error_card(
            "❌ العمل غير موجود", [f"العمل `{العمل}` غير موجود في القائمة."], avatar_url=avatar), ephemeral=True)
        return
    if is_work_isolated(target):
        await interaction.response.send_message(view=cards.info_card(
            "ℹ️ العمل معزول بالفعل", [f"العمل `{العمل}` معزول بالفعل."], avatar_url=avatar), ephemeral=True)
        return
    target["isolated"] = True
    target["isolated_at"] = datetime.utcnow().isoformat()
    target["isolated_by"] = str(interaction.user.id)
    if السبب:
        target["isolation_reason"] = السبب
    await save_works(works)
    await update_stats()
    await log_audit("عزل_عمل", interaction.user.id, None, f"عزل العمل {العمل} - السبب: {السبب or 'غير محدد'}")
    await interaction.response.send_message(view=cards.success_card(
        "⏸️ تم عزل العمل",
        [f"عُزل عمل «{العمل}» — لن تظهر فصوله في المستحقات والتقارير حتى يتم استرجاعه.",
         f"-# السبب: {السبب or 'غير محدد'}"],
        avatar_url=avatar), ephemeral=True)


@bot.tree.command(name="استرجاع_عمل", description="إلغاء عزل عمل وإعادته إلى الحسابات الظاهرة")
@app_commands.autocomplete(العمل=work_autocomplete)
@app_commands.describe(العمل="اسم العمل المطلوب استرجاعه")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def restore_work(interaction: discord.Interaction, العمل: str):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "استرجاع_عمل")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    works = await load_works()
    target = next((w for w in works if w["name"] == العمل), None)
    if not target:
        await interaction.response.send_message(view=cards.error_card(
            "❌ العمل غير موجود", [f"العمل `{العمل}` غير موجود في القائمة."], avatar_url=avatar), ephemeral=True)
        return
    if not is_work_isolated(target):
        await interaction.response.send_message(view=cards.info_card(
            "ℹ️ العمل غير معزول", [f"العمل `{العمل}` غير معزول حالياً."], avatar_url=avatar), ephemeral=True)
        return
    for key in ["isolated", "isolated_at", "isolated_by", "isolation_reason"]:
        target.pop(key, None)
    await save_works(works)
    await update_stats()
    await log_audit("استرجاع_عمل", interaction.user.id, None, f"استرجاع العمل {العمل} من العزل")
    await interaction.response.send_message(view=cards.success_card(
        "✅ تم استرجاع العمل",
        [f"عاد عمل «{العمل}» وظهرت فصوله في الحسابات والتقارير من جديد."],
        avatar_url=avatar), ephemeral=True)


# ═══════════════════════════════════════════════════════════════
# أسعار الأعمال المخصصة
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="تخصيص_سعر_عمل", description="تخصيص سعر تخصص معين لعمل محدد (استثناء عن السعر العام)")
@app_commands.autocomplete(العمل=work_autocomplete)
@app_commands.describe(العمل="اسم العمل", التخصص="اسم التخصص الذي تريد تخصيص سعره", السعر="السعر المخصص للفصل الواحد")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def set_work_specialty_price(interaction: discord.Interaction, العمل: str, التخصص: str, السعر: float):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "تخصيص_سعر_عمل")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return

    works = await load_works()
    target = next((w for w in works if w["name"] == العمل), None)
    if not target:
        await interaction.response.send_message(view=cards.error_card(
            "❌ العمل غير موجود", [f"العمل `{العمل}` غير موجود."], avatar_url=avatar), ephemeral=True)
        return

    norm_specialty = map_type(التخصص)
    if "custom_prices" not in target:
        target["custom_prices"] = {}
    target["custom_prices"][norm_specialty] = السعر
    await save_works(works)

    await log_audit("تخصيص_سعر_عمل", interaction.user.id, None,
                    f"تخصيص سعر تخصص {norm_specialty} لعمل {العمل} -> {السعر}")
    await interaction.response.send_message(view=cards.success_card(
        "✅ تم تخصيص السعر",
        [f"التخصص **{norm_specialty.replace('_', ' ').title()}** في عمل «{العمل}» ← سعر خاص **{السعر}**.",
         "-# يسري هذا السعر على هذا العمل فقط."],
        avatar_url=avatar), ephemeral=True)


@bot.tree.command(name="الغاء_تخصيص_عمل", description="إزالة التخصيصات السعرية لعمل وإعادته إلى الأسعار العامة")
@app_commands.autocomplete(العمل=work_autocomplete)
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def remove_work_specialty_prices(interaction: discord.Interaction, العمل: str):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "الغاء_تخصيص_عمل")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return

    works = await load_works()
    target = next((w for w in works if w["name"] == العمل), None)
    if not target:
        await interaction.response.send_message(view=cards.error_card(
            "❌ العمل غير موجود", [f"العمل `{العمل}` غير موجود."], avatar_url=avatar), ephemeral=True)
        return

    if "custom_prices" not in target:
        await interaction.response.send_message(view=cards.info_card(
            "ℹ️ لا تخصيصات", [f"العمل `{العمل}` ليس له تخصيصات سعرية أصلاً."], avatar_url=avatar), ephemeral=True)
        return

    del target["custom_prices"]
    await save_works(works)

    await log_audit("الغاء_تخصيص_عمل", interaction.user.id, None,
                    f"إزالة كل التخصيصات السعرية من عمل {العمل}")
    await interaction.response.send_message(view=cards.success_card(
        "✅ تم إلغاء التخصيصات",
        [f"أُزيلت جميع التخصيصات السعرية من «{العمل}» وسيعود إلى الأسعار العامة."],
        avatar_url=avatar), ephemeral=True)


@bot.tree.command(name="عرض_تخصيصات_عمل", description="عرض التخصصات ذات الأسعار المخصصة لعمل معين")
@app_commands.autocomplete(العمل=work_autocomplete)
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def show_work_specialties(interaction: discord.Interaction, العمل: str):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "عرض_تخصيصات_عمل")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return

    work = await get_work(العمل)
    if not work:
        await interaction.response.send_message(view=cards.error_card(
            "❌ العمل غير موجود", [f"العمل `{العمل}` غير موجود."], avatar_url=avatar), ephemeral=True)
        return

    custom = work.get("custom_prices")
    if not custom:
        await interaction.response.send_message(view=cards.info_card(
            "ℹ️ لا تخصيصات", [f"العمل `{العمل}` يخضع للأسعار العامة وليس له تخصيصات خاصة."],
            avatar_url=avatar), ephemeral=True)
        return

    bullets = "\n".join(f"• **{spec.replace('_', ' ').title()}** — {price}" for spec, price in custom.items())
    children = [
        cards.header([f"## 📌 تخصيصات عمل «{cards.clamp(العمل, 60)}»", f"**{len(custom)}** تخصصات بسعر خاص."], avatar),
        cards.sep(2),
        cards.text(bullets),
        cards.sep(),
        cards.text(f"-# {cards.BOT_SIGNATURE}"),
    ]
    await interaction.response.send_message(view=cards.Card(cards.ACCENT_GOLD, *children))


@bot.tree.command(name="نقل_تخصص_للخاص", description="نقل تخصص من القائمة العامة ليكون خاصاً بعمل محدد (يُزال من العامة)")
@app_commands.autocomplete(العمل=work_autocomplete, التخصص=specialty_autocomplete)
@app_commands.describe(العمل="اسم العمل الذي سيصبح التخصص خاصاً به", التخصص="اسم التخصص العام المراد نقله")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def move_specialty_to_work(interaction: discord.Interaction, العمل: str, التخصص: str):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "نقل_تخصص_للخاص")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return

    norm_specialty = map_type(التخصص)
    specialties = SETTINGS.get("specialties", {})
    if norm_specialty not in specialties:
        await interaction.response.send_message(view=cards.error_card(
            "❌ التخصص غير موجود", [f"التخصص `{التخصص}` غير موجود في التخصصات العامة."], avatar_url=avatar), ephemeral=True)
        return
    if not specialties[norm_specialty].get("active", True):
        await interaction.response.send_message(view=cards.error_card(
            "❌ التخصص معطّل", [f"التخصص `{التخصص}` معطّل حالياً في القائمة العامة."], avatar_url=avatar), ephemeral=True)
        return

    works = await load_works()
    target_work = next((w for w in works if w["name"] == العمل), None)
    if not target_work:
        await interaction.response.send_message(view=cards.error_card(
            "❌ العمل غير موجود", [f"العمل `{العمل}` غير موجود."], avatar_url=avatar), ephemeral=True)
        return

    current_price = specialties[norm_specialty]["price"]
    del specialties[norm_specialty]
    await save_settings(SETTINGS)
    rebuild_prices()

    if "custom_prices" not in target_work:
        target_work["custom_prices"] = {}
    target_work["custom_prices"][norm_specialty] = current_price
    await save_works(works)

    await log_audit("نقل_تخصص_للخاص", interaction.user.id, None,
                    f"نقل تخصص {norm_specialty} من العامة إلى عمل {العمل} بسعر {current_price}")
    await interaction.response.send_message(view=cards.success_card(
        "✅ تم نقل التخصص",
        [f"انتقل **{norm_specialty.replace('_', ' ').title()}** من العامة إلى «{العمل}».",
         f"السعر المخصص: **{current_price}** (نفس السعر العام السابق)."],
        avatar_url=avatar), ephemeral=True)


@bot.tree.command(name="نقل_تخصص_للعام", description="نقل تخصص خاص بعمل ليصبح تخصصاً عاماً من جديد")
@app_commands.autocomplete(العمل=work_autocomplete)
@app_commands.describe(العمل="اسم العمل الذي يحتوي التخصص الخاص", التخصص="اسم التخصص الموجود ضمن تخصيصات العمل")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def move_specialty_to_global(interaction: discord.Interaction, العمل: str, التخصص: str):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "نقل_تخصص_للعام")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return

    norm_specialty = map_type(التخصص)
    works = await load_works()
    target_work = next((w for w in works if w["name"] == العمل), None)
    if not target_work:
        await interaction.response.send_message(view=cards.error_card(
            "❌ العمل غير موجود", [f"العمل `{العمل}` غير موجود."], avatar_url=avatar), ephemeral=True)
        return

    custom = target_work.get("custom_prices")
    if not custom or norm_specialty not in custom:
        await interaction.response.send_message(view=cards.error_card(
            "❌ التخصص غير موجود",
            [f"التخصص `{norm_specialty}` غير موجود ضمن تخصيصات العمل `{العمل}`."], avatar_url=avatar), ephemeral=True)
        return

    price = custom[norm_specialty]
    del custom[norm_specialty]
    if not custom:
        del target_work["custom_prices"]
    await save_works(works)

    specialties = SETTINGS.get("specialties", {})
    specialties[norm_specialty] = {
        "price": price,
        "active": True,
        "last_modified": datetime.utcnow().isoformat()
    }
    await save_settings(SETTINGS)
    rebuild_prices()

    await log_audit("نقل_تخصص_للعام", interaction.user.id, None,
                    f"نقل تخصص {norm_specialty} من عمل {العمل} إلى العامة بسعر {price}")
    await interaction.response.send_message(view=cards.success_card(
        "✅ تم نقل التخصص",
        [f"انتقل **{norm_specialty.replace('_', ' ').title()}** من «{العمل}» إلى التخصصات العامة.",
         f"السعر العام الآن: **{price}**"],
        avatar_url=avatar), ephemeral=True)


# ═══════════════════════════════════════════════════════════════
# إدارة التخصصات
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="اضافة_تخصص", description="إضافة تخصص جديد (للمشرفين)")
@app_commands.describe(الاسم="اسم التخصص (مثال: تدقيق)", السعر="سعر الفصل الواحد", نشط="مفعل؟")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def add_specialty(interaction: discord.Interaction, الاسم: str, السعر: float, نشط: bool = True):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "اضافة_تخصص")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    norm_name = map_type(الاسم)
    if norm_name in SETTINGS.get("specialties", {}):
        await interaction.response.send_message(view=cards.error_card(
            "❌ التخصص موجود مسبقاً", [f"التخصص `{norm_name}` موجود بالفعل."], avatar_url=avatar), ephemeral=True)
        return
    SETTINGS["specialties"][norm_name] = {
        "price": السعر,
        "active": نشط,
        "last_modified": datetime.utcnow().isoformat()
    }
    await save_settings(SETTINGS)
    rebuild_prices()
    await log_audit("اضافة_تخصص", interaction.user.id, None, f"أضاف تخصص {norm_name} بسعر {السعر}")
    await interaction.response.send_message(view=cards.success_card(
        "✅ تم إضافة التخصص",
        [f"**{norm_name.replace('_', ' ').title()}** — السعر: **{السعر}** — الحالة: {'نشط ✅' if نشط else 'معطل ⊘'}"],
        avatar_url=avatar), ephemeral=True)


@bot.tree.command(name="حذف_تخصص", description="حذف (تعطيل) تخصص (للمشرفين)")
@app_commands.autocomplete(الاسم=specialty_autocomplete)
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def delete_specialty(interaction: discord.Interaction, الاسم: str):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "حذف_تخصص")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    norm_name = map_type(الاسم)
    if norm_name not in SETTINGS.get("specialties", {}):
        await interaction.response.send_message(view=cards.error_card(
            "❌ التخصص غير موجود", [f"التخصص `{الاسم}` غير موجود."], avatar_url=avatar), ephemeral=True)
        return
    SETTINGS["specialties"][norm_name]["active"] = False
    await save_settings(SETTINGS)
    rebuild_prices()
    await log_audit("حذف_تخصص", interaction.user.id, None, f"عطّل تخصص {norm_name}")
    await interaction.response.send_message(view=cards.success_card(
        "✅ تم تعطيل التخصص",
        [f"التخصص **{norm_name.replace('_', ' ').title()}** معطّل الآن ولن يظهر في أوامر التسجيل."],
        avatar_url=avatar), ephemeral=True)


@bot.tree.command(name="تفعيل_تخصص", description="تفعيل تخصص معطل (للمشرفين)")
@app_commands.autocomplete(الاسم=specialty_autocomplete)
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def activate_specialty(interaction: discord.Interaction, الاسم: str):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "تفعيل_تخصص")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    norm_name = map_type(الاسم)
    specialties = SETTINGS.get("specialties", {})
    if norm_name not in specialties:
        await interaction.response.send_message(view=cards.error_card(
            "❌ التخصص غير موجود", [f"التخصص `{الاسم}` غير موجود."], avatar_url=avatar), ephemeral=True)
        return
    specialties[norm_name]["active"] = True
    await save_settings(SETTINGS)
    rebuild_prices()
    await interaction.response.send_message(view=cards.success_card(
        "✅ تم تفعيل التخصص",
        [f"التخصص **{norm_name.replace('_', ' ').title()}** مفعّل الآن."],
        avatar_url=avatar), ephemeral=True)


@bot.tree.command(name="تعطيل_تخصص", description="تعطيل تخصص (للمشرفين)")
@app_commands.autocomplete(الاسم=specialty_autocomplete)
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def deactivate_specialty(interaction: discord.Interaction, الاسم: str):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "تعطيل_تخصص")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    norm_name = map_type(الاسم)
    specialties = SETTINGS.get("specialties", {})
    if norm_name not in specialties:
        await interaction.response.send_message(view=cards.error_card(
            "❌ التخصص غير موجود", [f"التخصص `{الاسم}` غير موجود."], avatar_url=avatar), ephemeral=True)
        return
    specialties[norm_name]["active"] = False
    await save_settings(SETTINGS)
    rebuild_prices()
    await interaction.response.send_message(view=cards.success_card(
        "✅ تم تعطيل التخصص",
        [f"التخصص **{norm_name.replace('_', ' ').title()}** معطّل الآن."],
        avatar_url=avatar), ephemeral=True)


# ═══════════════════════════════════════════════════════════════
# المكافآت والخصومات
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="مكافأة", description="إضافة مكافأة (مبلغ موجب) لعضو - للإدارة فقط")
@app_commands.describe(عضو="العضو المستحق للمكافأة", المبلغ="المبلغ الموجب المراد إضافته", السبب="سبب المكافأة (اختياري)")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def add_bonus(interaction: discord.Interaction, عضو: discord.Member, المبلغ: float, السبب: str = None):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "مكافأة")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    if المبلغ <= 0:
        await interaction.response.send_message(view=cards.error_card(
            "❌ مبلغ غير صالح", ["المبلغ يجب أن يكون أكبر من صفر."], avatar_url=avatar), ephemeral=True)
        return

    records = await load_records()
    user_id = str(عضو.id)
    if user_id not in records:
        records[user_id] = []

    bonus_entry = {
        "work_name": "نظام المكافآت والخصومات",
        "chapter": "مكافأة",
        "work_type": "مكافأة",
        "total": abs(المبلغ),
        "notes": السبب or "",
        "timestamp": datetime.utcnow().isoformat(),
        "username": عضو.name,
        "added_by": str(interaction.user.id)
    }
    records[user_id].append(bonus_entry)
    await save_records(records)
    await update_stats()

    currency = SETTINGS.get('currency', '$') or '$'
    lines = [f"**👤 العضو:** {عضو.mention}",
             f"**💰 المبلغ:** {currency}{abs(المبلغ):.2f}"]
    if السبب:
        lines.append(f"**📝 السبب:** {السبب}")
    lines.append(f"**🛡️ أضيفت بواسطة:** {interaction.user.mention}")
    children = [
        cards.header(["## 🎁 تمت إضافة المكافأة", f"<@{عضو.id}>"], avatar),
        cards.sep(2),
        cards.text("\n".join(lines)),
        cards.sep(),
        cards.text(f"-# {cards.BOT_SIGNATURE}"),
    ]
    await interaction.response.send_message(view=cards.Card(cards.ACCENT_GREEN, *children))

    await log_audit("مكافأة", interaction.user.id, عضو.id, f"مكافأة {abs(المبلغ):.2f} - السبب: {السبب or 'غير محدد'}")
    try:
        await عضو.send(f"🎁 لقد تلقيت مكافأة بقيمة {currency}{abs(المبلغ):.2f} من {interaction.user.mention}.\nالسبب: {السبب or 'غير محدد'}")
    except:
        pass


@bot.tree.command(name="خصم", description="خصم مبلغ (سالب) من عضو - للإدارة فقط")
@app_commands.describe(عضو="العضو المراد الخصم منه", المبلغ="المبلغ الموجب (سيتم خصمه)", السبب="سبب الخصم (اختياري)")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def add_deduction(interaction: discord.Interaction, عضو: discord.Member, المبلغ: float, السبب: str = None):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "خصم")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    if المبلغ <= 0:
        await interaction.response.send_message(view=cards.error_card(
            "❌ مبلغ غير صالح", ["المبلغ يجب أن يكون أكبر من صفر."], avatar_url=avatar), ephemeral=True)
        return

    records = await load_records()
    user_id = str(عضو.id)
    if user_id not in records:
        records[user_id] = []

    deduction_entry = {
        "work_name": "نظام المكافآت والخصومات",
        "chapter": "خصم",
        "work_type": "خصم",
        "total": -abs(المبلغ),
        "notes": السبب or "",
        "timestamp": datetime.utcnow().isoformat(),
        "username": عضو.name,
        "added_by": str(interaction.user.id)
    }
    records[user_id].append(deduction_entry)
    await save_records(records)
    await update_stats()

    currency = SETTINGS.get('currency', '$') or '$'
    lines = [f"**👤 العضو:** {عضو.mention}",
             f"**💸 المبلغ المخصوم:** {currency}{abs(المبلغ):.2f}"]
    if السبب:
        lines.append(f"**📝 السبب:** {السبب}")
    lines.append(f"**🛡️ أضيف بواسطة:** {interaction.user.mention}")
    children = [
        cards.header(["## 🔻 تم الخصم", f"<@{عضو.id}>"], avatar),
        cards.sep(2),
        cards.text("\n".join(lines)),
        cards.sep(),
        cards.text(f"-# {cards.BOT_SIGNATURE}"),
    ]
    await interaction.response.send_message(view=cards.Card(cards.ACCENT_RED, *children))

    await log_audit("خصم", interaction.user.id, عضو.id, f"خصم {abs(المبلغ):.2f} - السبب: {السبب or 'غير محدد'}")
    try:
        await عضو.send(f"🔻 تم خصم مبلغ {currency}{abs(المبلغ):.2f} من رصيدك بواسطة {interaction.user.mention}.\nالسبب: {السبب or 'غير محدد'}")
    except:
        pass


@bot.tree.command(name="حذف_مكافأة_خصم", description="حذف مكافأة أو خصم سابق لعضو - للإدارة فقط")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def delete_bonus_deduction(interaction: discord.Interaction, عضو: discord.Member):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "حذف_مكافأة_خصم")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    records = await load_records()
    user_id = str(عضو.id)
    if user_id not in records:
        await interaction.response.send_message(view=cards.error_card(
            "❌ لا توجد سجلات", [f"لا يوجد سجلات للعضو {عضو.mention}."], avatar_url=avatar), ephemeral=True)
        return

    all_entries = records[user_id]
    bonus_ded_entries = [e for e in all_entries if e.get("work_type") in ("مكافأة", "خصم")]
    bonus_ded_entries.reverse()  # newest first
    recent = bonus_ded_entries[:10]
    if not recent:
        await interaction.response.send_message(view=cards.error_card(
            "❌ لا توجد عمليات", [f"لا يوجد عمليات مكافأة أو خصم للعضو {عضو.mention}."], avatar_url=avatar), ephemeral=True)
        return

    options = []
    for i, e in enumerate(recent):
        desc = f"{e.get('work_type')} {abs(e.get('total', 0)):.2f} - {e.get('notes','')[:50]}"
        options.append(discord.SelectOption(label=cards.clamp(f"{i+1}. {desc}", 100), value=str(i)))
    options.append(discord.SelectOption(label="❌ إلغاء", value="cancel"))

    view = BonusDeletePanel(interaction.user, عضو, recent, options)
    await interaction.response.send_message(view=view)


class BonusDeletePanel(ui.LayoutView):
    def __init__(self, moderator, member, recent, options):
        super().__init__(timeout=120.0)
        self.moderator = moderator
        self.member = member
        self.recent = recent
        self.options = options
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        children: list = [
            cards.header(["## ⚖️ عمليات المكافآت والخصومات", f"**{self.member.mention}** — أحدث 10 عمليات."],
                         _bot_avatar()),
            cards.sep(2),
            cards.make_select("اختر العملية للحذف...", self.options, self.select_callback),
            cards.sep(),
            cards.text(f"-# {cards.BOT_SIGNATURE}"),
        ]
        self.add_item(cards.Card(cards.ACCENT_GOLD, *children))

    async def select_callback(self, interaction: discord.Interaction):
        value = interaction.data['values'][0]
        if value == "cancel":
            await interaction.response.edit_message(view=cards.muted_card(
                "🚫 أُلغيت العملية", ["لم يُحذف أي شيء."], avatar_url=_bot_avatar()))
            return
        idx = int(value)
        entry_to_delete = self.recent[idx]

        async def confirm(interaction2: discord.Interaction):
            records2 = await load_records()
            if str(self.member.id) in records2:
                new_entries = []
                removed = False
                for e in records2[str(self.member.id)]:
                    if not removed and e == entry_to_delete:
                        removed = True
                        continue
                    new_entries.append(e)
                if removed:
                    records2[str(self.member.id)] = new_entries
                    if not records2[str(self.member.id)]:
                        del records2[str(self.member.id)]
                    await save_records(records2)
                    await log_audit("حذف_مكافأة_خصم", interaction.user.id, self.member.id,
                                    f"حذف {entry_to_delete.get('work_type')} {abs(entry_to_delete.get('total',0)):.2f}")
                    await update_stats()
                    await _finish(interaction2, "✅ تم حذف العملية",
                                  [f"حُذفت عملية **{entry_to_delete.get('work_type')}** بمبلغ "
                                   f"{abs(entry_to_delete.get('total',0)):.2f}."])
                else:
                    await _finish(interaction2, "❌ لم يتم العثور على العملية",
                                  ["لم يتم العثور على العملية — ربما حُذفت للتو."], gray=True)
            else:
                await _finish(interaction2, "❌ لا توجد سجلات", ["لا توجد سجلات."], gray=True)

        await _confirm_card(interaction, "⚠️ تأكيد الحذف",
                            f"تأكيد حذف **{entry_to_delete.get('work_type')}** بمبلغ "
                            f"{abs(entry_to_delete.get('total',0)):.2f}؟", confirm)


# ═══════════════════════════════════════════════════════════════
# موعد الدفع + تقرير الدفع
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="تحديد_موعد_الدفع", description="تحديد يوم وساعة الدفع الشهري (للمشرفين)")
@app_commands.describe(اليوم="يوم الشهر (1-28)", الساعة="الساعة (0-23)، افتراضي 0")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def set_payment_day(interaction: discord.Interaction, اليوم: int, الساعة: int = 0):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "تحديد_موعد_الدفع")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    if not (1 <= اليوم <= 28):
        await interaction.response.send_message(view=cards.error_card(
            "❌ يوم غير صالح", ["اليوم يجب أن يكون بين 1 و 28."], avatar_url=avatar), ephemeral=True)
        return
    if not (0 <= الساعة <= 23):
        await interaction.response.send_message(view=cards.error_card(
            "❌ ساعة غير صالحة", ["الساعة يجب أن تكون بين 0 و 23."], avatar_url=avatar), ephemeral=True)
        return
    SETTINGS["payment_day"] = اليوم
    SETTINGS["payment_hour"] = الساعة
    SETTINGS["payment_reminder_24h_sent"] = False
    SETTINGS["payment_day_sent"] = False
    await save_settings(SETTINGS)
    await interaction.response.send_message(view=cards.success_card(
        "✅ تم تعيين موعد الدفع",
        [f"موعد الدفع الشهري: **يوم {اليوم} الساعة {الساعة}:00**.",
         "-# ستصلا بطاقة تذكير قبل الموعد بـ 24 ساعة ثم في يومه."],
        avatar_url=avatar), ephemeral=True)
    await log_audit("تحديد_موعد_الدفع", interaction.user.id, None, f"يوم {اليوم} ساعة {الساعة}")


class PaymentReportPaginator(ui.LayoutView):
    def __init__(self, rows, details, guild, currency):
        super().__init__(timeout=300.0)
        self.rows = rows
        self.details = details
        self.guild = guild
        self.currency = currency or '$'
        self.current_page = 0
        self.per_page = 6
        self.total_pages = max(1, (len(rows) + self.per_page - 1) // self.per_page)
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        avatar = _bot_avatar()
        children: list = [
            cards.header(["## 📅 تقرير الدفع الشهري", self._summary_line()], avatar),
            cards.sep(2),
        ]
        start = self.current_page * self.per_page
        page_rows = self.rows[start:start + self.per_page]
        blocks = []
        for index, row in enumerate(page_rows, start + 1):
            works_preview = "، ".join(f"{name} ({count})" for name, count in row["works"][:4]) or "لا توجد أعمال"
            blocks.append(
                f"**{index}. {row['name']}**\n"
                f"{row['mention']}\n"
                f"-# 📑 الفصول: **{row['chapters']}** | 🎁 المكافآت: {self.currency}{row['bonuses']:.2f} | 🔻 الخصومات: {self.currency}{row['deductions']:.2f}\n"
                f"-# 💵 الصافي المستحق: **{self.currency}{row['total']:.2f}**\n"
                f"-# 📚 الأعمال: {works_preview}"
            )
        children.append(cards.text(cards.clamp("\n\n".join(blocks), 3200)))
        footnote = "مرتّب حسب صافي المستحق • الأعمال المعزولة مستبعدة."
        children += [cards.sep(), cards.text(f"-# {footnote}")]
        if self.total_pages > 1:
            children += [cards.sep(), cards.pager_row(self.current_page, self.total_pages,
                                                      self.previous_page, self.next_page)]
        children += [cards.sep(), cards.row(
            cards.success_btn("📥 تصدير Excel", self.export_excel)
        ), cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
        self.add_item(cards.Card(cards.ACCENT_GOLD, *children))

    def _summary_line(self) -> str:
        grand_total = sum(row["total"] for row in self.rows)
        total_chapters = sum(row["chapters"] for row in self.rows)
        return f"**الأعضاء:** {len(self.rows)} • **الفصول:** {total_chapters} • **الإجمالي:** {self.currency}{grand_total:.2f}"

    async def refresh(self, interaction: discord.Interaction):
        self.rebuild()
        await interaction.response.edit_message(view=self)

    async def previous_page(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        await self.refresh(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        await self.refresh(interaction)

    async def export_excel(self, interaction: discord.Interaction):
        rows = []
        for user_id, entries in self.details.items():
            user = self.guild.get_member(int(user_id))
            username = user.display_name if user else user_id
            for entry in entries:
                rows.append({
                    "اسم العضو": username,
                    "معرف العضو": user_id,
                    "العمل": entry.get("work_name"),
                    "الفصل": entry.get("chapter"),
                    "التخصص": entry.get("work_type"),
                    "المبلغ": entry.get("total"),
                    "ملاحظات": entry.get("notes"),
                    "التاريخ": entry.get("timestamp", "")
                })
        df = pd.DataFrame(rows)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name="تقرير_الشهر")
        buffer.seek(0)
        await interaction.response.send_message(file=discord.File(buffer, filename=f"payment_report_{datetime.utcnow().date()}.xlsx"), ephemeral=True)


@bot.tree.command(name="تقرير_دفع", description="تقرير الدفع الشهري مع خيار تصدير Excel")
@app_commands.checks.cooldown(1, 10, key=lambda i: (i.user.id, i.command.qualified_name))
async def payment_report(interaction: discord.Interaction):
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "تقرير_دفع")
        await interaction.response.send_message(view=cards.permission_card(_bot_avatar()), ephemeral=True)
        return
    records = await load_visible_records()
    month_start = datetime.utcnow().replace(day=1)
    totals = {}
    details = {}
    rows = []
    for user_id, entries in records.items():
        user_total = 0
        user_entries = []
        chapters = 0
        bonuses = 0
        deductions = 0
        works_count = defaultdict(int)
        for e in entries:
            try:
                entry_date = datetime.fromisoformat(e["timestamp"])
                if entry_date >= month_start:
                    user_total += e.get("total", 0)
                    user_entries.append(e)
                    if e.get("work_type") == "مكافأة":
                        bonuses += e.get("total", 0)
                    elif e.get("work_type") == "خصم":
                        deductions += abs(e.get("total", 0))
                    else:
                        chapters += 1
                        works_count[e.get("work_name", "غير محدد")] += 1
            except:
                pass
        if user_entries:
            totals[user_id] = user_total
            details[user_id] = user_entries
            user = interaction.guild.get_member(int(user_id))
            username_hint = next((e.get("username") for e in user_entries if e.get("username")), None)
            rows.append({
                "user_id": user_id,
                "mention": f"<@{user_id}>",
                "name": user.display_name if user else (username_hint or user_id),
                "total": user_total,
                "chapters": chapters,
                "bonuses": bonuses,
                "deductions": deductions,
                "works": sorted(works_count.items(), key=lambda item: item[1], reverse=True),
            })
    if not totals:
        await interaction.response.send_message(view=cards.info_card(
            "📭 لا توجد سجلات", ["لا توجد أي سجلات لهذا الشهر."], avatar_url=_bot_avatar()), ephemeral=True)
        return

    rows.sort(key=lambda row: row["total"], reverse=True)
    view = PaymentReportPaginator(rows, details, interaction.guild, SETTINGS.get('currency', '$'))
    await interaction.response.send_message(view=view)


# ═══════════════════════════════════════════════════════════════
# /ملخص_شهري للأعضاء
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="ملخص_شهري", description="ملخص شغلك للشهر الحالي")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def monthly_summary(interaction: discord.Interaction):
    if interaction.channel.name not in SETTINGS.get("allowed_channels", []):
        await interaction.response.send_message(
            view=cards.channel_card(SETTINGS.get("allowed_channels", []), _bot_avatar()), ephemeral=True)
        return
    avatar = _bot_avatar()
    records = await load_visible_records()
    user_id = str(interaction.user.id)
    if user_id not in records:
        await interaction.response.send_message(view=cards.info_card(
            "📭 ليس لديك أي شغل", ["لم تسجل أي فصول بعد — ابدأ بأمر /تسجيل."], avatar_url=avatar), ephemeral=True)
        return
    month_start = datetime.utcnow().replace(day=1)
    month_entries = [e for e in records[user_id] if "timestamp" in e and datetime.fromisoformat(e["timestamp"]) >= month_start]
    if not month_entries:
        await interaction.response.send_message(view=cards.info_card(
            "📭 لا يوجد عمل هذا الشهر", ["لم تقم بأي عمل هذا الشهر."], avatar_url=avatar), ephemeral=True)
        return
    total = sum(e.get("total", 0) for e in month_entries)
    works_count = defaultdict(int)
    for e in month_entries:
        works_count[e.get("work_name", "غير محدد")] += 1
    details_str = "\n".join([f"• **{w}:** {c} فصول" for w, c in works_count.items()])
    currency = SETTINGS.get('currency', '$') or '$'
    children = [
        cards.header(["## 📆 ملخصك الشهري", f"<@{interaction.user.id}>"], avatar),
        cards.sep(2),
        cards.progress_line(len(month_entries), len(month_entries)),
        cards.sep(),
        cards.text(
            f"**عدد الفصول المنجزة:** {len(month_entries)}\n"
            f"**المبلغ المستحق:** {currency}{total:.2f}\n\n"
            f"**تفصيل الأعمال**\n{details_str}"
        ),
        cards.sep(),
        cards.text(f"-# من بداية الشهر حتى الآن • {cards.BOT_SIGNATURE}"),
    ]
    await interaction.response.send_message(view=cards.Card(cards.ACCENT_GOLD, *children))


# ═══════════════════════════════════════════════════════════════
# /تحديث_أسعار
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="تحديث_أسعار", description="تحديث مبالغ الفصول المسجلة بناءً على الأسعار الحالية (للمشرفين)")
@app_commands.autocomplete(التخصص=specialty_autocomplete)
@app_commands.describe(
    التخصص="تخصص محدد (اختياري، وإلا كل التخصصات)",
    من_تاريخ="بداية النطاق (YYYY-MM-DD، اختياري)",
    الى_تاريخ="نهاية النطاق (YYYY-MM-DD، اختياري)",
    كل_السجلات="تحديث كل السجلات بغض النظر عن التاريخ"
)
@app_commands.checks.cooldown(1, 10, key=lambda i: (i.user.id, i.command.qualified_name))
async def update_prices(interaction: discord.Interaction, التخصص: str = None, من_تاريخ: str = None, الى_تاريخ: str = None, كل_السجلات: bool = False):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "تحديث_أسعار")
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    records = await load_records()
    specialties = SETTINGS.get("specialties", {})
    updated_count = 0
    # Determine specialty filter
    target_specialty = map_type(التخصص) if التخصص else None
    if target_specialty and target_specialty not in specialties:
        await interaction.followup.send(view=cards.error_card(
            "❌ التخصص غير موجود", [f"التخصص `{التخصص}` غير موجود."], avatar_url=avatar), ephemeral=True)
        return
    # Determine date range
    if كل_السجلات:
        date_from = None
        date_to = None
    elif من_تاريخ or الى_تاريخ:
        try:
            date_from = datetime.fromisoformat(من_تاريخ) if من_تاريخ else datetime.min
            date_to = datetime.fromisoformat(الى_تاريخ) if الى_تاريخ else datetime.max
        except:
            await interaction.followup.send(view=cards.error_card(
                "❌ صيغة تاريخ غير صحيحة", ["استخدم صيغة YYYY-MM-DD."], avatar_url=avatar), ephemeral=True)
            return
    else:
        # Default: current month
        date_from = datetime.utcnow().replace(day=1)
        date_to = datetime.utcnow()
    # Iterate records and update
    for user_id, entries in records.items():
        for entry in entries:
            wtype = entry.get("work_type")
            if wtype not in specialties:
                continue
            if target_specialty and wtype != target_specialty:
                continue
            if not كل_السجلات:
                try:
                    entry_date = datetime.fromisoformat(entry.get("timestamp"))
                    if entry_date < date_from or entry_date > date_to:
                        continue
                except:
                    continue
            if specialties[wtype].get("active", True):
                entry["total"] = specialties[wtype]["price"]
                updated_count += 1
    await save_records(records)
    await update_stats()
    period_str = "كل السجلات" if كل_السجلات else f"{من_تاريخ or 'بداية الشهر'} ← {الى_تاريخ or 'الآن'}"
    await log_audit("تحديث_أسعار", interaction.user.id, None,
                    f"تم تحديث {updated_count} سجل - التخصص: {التخصص or 'الكل'}, الفترة: {period_str}")

    checklist = [
        f"✓ تحديث السجلات — {updated_count} سجل",
        f"✓ التخصص — {التخصص or 'كل التخصصات'}",
        f"✓ الفترة — {period_str}",
    ]
    children = [
        cards.header(["## ✅ تم تحديث الأسعار", f"<@{interaction.user.id}>"], avatar),
        cards.sep(2),
        cards.text("\n".join(checklist)),
        cards.sep(),
        cards.text(f"-# {cards.BOT_SIGNATURE}"),
    ]
    await interaction.followup.send(view=cards.Card(cards.ACCENT_GREEN, *children), ephemeral=True)
