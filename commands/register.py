from datetime import datetime
from typing import List, Optional
import discord
from discord import app_commands
from discord.ext import commands
from state import bot
from helpers.core import *
from tasks.lifecycle import work_autocomplete, registration_specialty_autocomplete
from ui import cards


def _user_avatar(user):
    """صورة العضو المعنيّ — تظهر في رأس الإيصال بدل صورة البوت."""
    try:
        return user.display_avatar.url if user else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# 🧾 بطاقة إيصال التسجيل — نفس بنية بطاقة العمل في بوت السحب:
#   رأس Section بصورة البوت + منشن الطالب + سطر التصنيف، فاصل،
#   شريط تقدم ▰▱ (عند وجود فصول متجاهلة)، قائمة مراحل ✓،
#   تفاصيل، سطر الإجمالي، وتذييل -# ZEUS.
# ═══════════════════════════════════════════════════════════════
def build_receipt_card(
    *,
    requester: discord.abc.User,
    added_by: Optional[discord.abc.User],
    work_name: str,
    added_chapters: List[str],
    total_input_chapters: int,
    free_count: int,
    duplicates_skipped: int,
    filtered_types: List[str],
    total_amount: float,
    notes: Optional[str],
    avatar_url: Optional[str],
) -> cards.Card:
    currency = SETTINGS.get('currency', '$') or '$'
    chapters_str = "، ".join(f"فصل {ch}" for ch in added_chapters) or "—"

    label_line = f"**{work_name}** — {chapters_str}"
    header_lines = ["## إيصال التسجيل جاهز", f"<@{requester.id}>", label_line]

    children: list = [cards.header(header_lines, avatar_url), cards.sep(2)]

    # شريط التقدم — يظهر فقط عند وجود فصول متجاهلة (مجانية/مكررة)
    skipped = free_count + duplicates_skipped
    if skipped > 0 or len(added_chapters) != total_input_chapters:
        children.append(cards.text(cards.progress_line(len(added_chapters), total_input_chapters)))
        children.append(cards.sep())

    # قائمة المراحل ✓ — نفس رموز بوت السحب
    check: List[str] = []
    check.append(f"✓ فحص العمل — «{work_name}»")
    filtered_note = f"{len(added_chapters) + duplicates_skipped} فصول مدفوعة"
    if free_count > 0:
        filtered_note += f" — {free_count} مجانية تجاهلت"
    check.append(f"✓ فلترة الفصول — {filtered_note}")
    check.append(f"✓ تسجيل الفصول — {len(added_chapters)} سجل جديد")
    check.append(f"✓ حساب المستحق — {currency}{total_amount:.2f}")
    children.append(cards.text("\n".join(check)))

    # تفاصيل التخصصات
    if len(set(filtered_types)) == 1:
        children += [cards.sep(), cards.text(f"**التخصص:** {filtered_types[0]}")]
    else:
        types_summary = "\n".join(f"• فصل {ch}: {t}" for ch, t in zip(added_chapters, filtered_types))
        children += [cards.sep(), cards.text(f"**تفاصيل التخصصات**\n{cards.clamp(types_summary, 900)}")]

    # سطر النتيجة النهائية
    final_lines = [f"**💰 الإجمالي:** {currency}{total_amount:.2f}"]
    if added_by and added_by.id != requester.id:
        final_lines.append(f"**أضيف بواسطة:** <@{added_by.id}>")
    if notes:
        final_lines.append(f"**الملاحظات:** {cards.clamp(notes, 300)}")
    children += [cards.sep(), cards.text("\n".join(final_lines))]

    children += [cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
    return cards.Card(cards.ACCENT_GOLD, *children)


# ═══════════════════════════════════════════════════════════════
# ⚙️ منطق التسجيل المشترك (نفس فلسفة بوت السحب: فحص ← فلترة ←
#   تسجيل ← حساب، مع بطاقة فشل حمراء لكل سبب رفض)
# ═══════════════════════════════════════════════════════════════
async def validate_registration(
    interaction: discord.Interaction,
    work_name: str,
    chapters_input: str,
    types_input: str,
) -> tuple:
    """يرجع (work, chapters_list, paid_chapters, free_count, filtered_types) أو (None,...,error_card)."""
    avatar_url = interaction.client.user.display_avatar.url if interaction.client.user else None

    work = await get_work(work_name)
    if not work:
        return None, None, None, 0, None, cards.error_card(
            "تعذر بدء التسجيل",
            [f"العمل `{work_name}` غير موجود في قائمة الأعمال المدفوعة. تواصل مع الإدارة."],
            avatar_url=avatar_url)
    if not work.get("active", True):
        return None, None, None, 0, None, cards.error_card(
            "تعذر بدء التسجيل",
            [f"العمل `{work_name}` معطل حالياً."],
            avatar_url=avatar_url)
    if is_work_isolated(work):
        return None, None, None, 0, None, cards.error_card(
            "تعذر بدء التسجيل",
            [f"العمل `{work_name}` معزول حالياً عن التسجيل والحسابات حتى تسترجعه الإدارة."],
            avatar_url=avatar_url)

    chapters_list = parse_chapter_range(chapters_input)
    if not chapters_list:
        return None, None, None, 0, None, cards.error_card(
            "تعذر بدء التسجيل",
            ["نطاق الفصول غير صالح. استخدم مثلاً `5` أو `1-5` أو `1,3,5`."],
            avatar_url=avatar_url)

    paid_chapters, free_count = filter_paid_chapters(work, chapters_list)
    if not paid_chapters:
        return None, None, None, 0, None, cards.error_card(
            "جميع الفصول مجانية",
            ["جميع الفصول المدخلة مجانية ولم تُسجّل."],
            avatar_url=avatar_url)

    original_types = parse_mixed_types(types_input, len(chapters_list))
    if original_types is None:
        return None, None, None, 0, None, cards.error_card(
            "تعذر بدء التسجيل",
            [f"عدد التخصصات لا يتطابق مع عدد الفصول ({len(chapters_list)})."],
            avatar_url=avatar_url)

    mapped_types = [map_type(t) for t in original_types]

    filtered_types = []
    kept_set = set(paid_chapters)
    for idx, ch in enumerate(chapters_list):
        if ch in kept_set:
            filtered_types.append(mapped_types[idx])

    # التحقق من صحة التخصصات
    if "custom_prices" in work and isinstance(work["custom_prices"], dict):
        allowed_specs = list(work["custom_prices"].keys())
        for t in filtered_types:
            if t not in allowed_specs:
                return None, None, None, 0, None, cards.error_card(
                    "تعذر بدء التسجيل",
                    [f"التخصص `{t}` غير مسموح به في عمل `{work_name}`.\n"
                     f"التخصصات المتاحة لهذا العمل: {', '.join(allowed_specs)}"],
                    avatar_url=avatar_url)
    else:
        for t in filtered_types:
            if t not in PRICES:
                return None, None, None, 0, None, cards.error_card(
                    "تعذر بدء التسجيل",
                    [f"التخصص `{t}` غير صحيح. التخصصات المتاحة: {', '.join(PRICES.keys())}"],
                    avatar_url=avatar_url)

    return work, chapters_list, paid_chapters, free_count, filtered_types, None


# ═══════════════════════════════════════════════════════════════
# أوامر التسجيل
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="تسجيل", description="تسجيل فصول منجزة واستلام إيصال جاهز بالحساب")
@app_commands.autocomplete(العمل=work_autocomplete, التخصصات=registration_specialty_autocomplete)
@app_commands.describe(
    العمل="اسم العمل (اختر من القائمة)",
    الفصول="نطاق الفصول مثل 1-5 أو 1,3,5",
    التخصصات="التخصصات مثل ترجمة كوري-تحرير-تبييض (بدون شرطة سفلية)",
    ملاحظات="ملاحظات اختيارية"
)
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def register_slash(interaction: discord.Interaction, العمل: str, الفصول: str, التخصصات: str, ملاحظات: str = None):
    avatar_url = interaction.client.user.display_avatar.url if interaction.client.user else None
    if not channel_allowed(interaction):
        await interaction.response.send_message(view=cards.channel_card(SETTINGS.get("allowed_channels", []), avatar_url), ephemeral=True)
        return

    work, chapters_list, paid_chapters, free_count, filtered_types, error_card = await validate_registration(
        interaction, العمل, الفصول, التخصصات)
    if error_card is not None:
        await interaction.response.send_message(view=error_card, ephemeral=True)
        return

    records = await load_records()
    user_id = str(interaction.user.id)
    if user_id not in records:
        records[user_id] = []

    added_chapters_list = []
    added_types_list = []
    username = interaction.user.name
    duplicates_skipped = 0
    month_key = get_active_month_key()
    for idx, ch in enumerate(paid_chapters):
        work_type = filtered_types[idx]
        if is_duplicate(records, user_id, العمل, ch, work_type):
            duplicates_skipped += 1
            continue
        total = await get_specialty_price(العمل, work_type)
        records[user_id].append({
            "work_name": العمل,
            "chapter": ch,
            "work_type": work_type,
            "total": total,
            "notes": ملاحظات or "",
            "timestamp": datetime.utcnow().isoformat(),
            "month_key": month_key,
            "username": username
        })
        added_chapters_list.append(ch)
        added_types_list.append(work_type)

    added = len(added_chapters_list)
    if added == 0:
        await interaction.response.send_message(view=cards.error_card(
            "لم يُسجّل شيء جديد",
            ["لم يتم إضافة أي فصل جديد (جميع الفصول إما مكررة أو مجانية)."],
            avatar_url=avatar_url), ephemeral=True)
        return

    saved = await save_records(records)
    if not saved:
        await interaction.response.send_message(view=cards.error_card(
            "تعذر الحفظ",
            ["قاعدة البيانات غير متاحة الآن.",
             "لم تُسجل بياناتك — **لم يُفقد شيء** — أعد المحاولة بعد قليل."],
            avatar_url=avatar_url), ephemeral=True)
        return
    await update_stats()
    await upsert_member(interaction.user.id, interaction.user.name)

    if added_types_list and len(set(added_types_list)) == 1:
        total_amount = added * await get_specialty_price(العمل, added_types_list[0])
    else:
        total_amount = sum([await get_specialty_price(العمل, t) for t in added_types_list])

    receipt = build_receipt_card(
        requester=interaction.user,
        added_by=None,
        work_name=العمل,
        added_chapters=added_chapters_list,
        total_input_chapters=len(chapters_list),
        free_count=free_count,
        duplicates_skipped=duplicates_skipped,
        filtered_types=added_types_list,
        total_amount=total_amount,
        notes=ملاحظات,
        avatar_url=_user_avatar(interaction.user),
    )
    await interaction.response.send_message(view=receipt)

    notify_channel_id = SETTINGS.get("notify_channel_id")
    if notify_channel_id:
        channel = interaction.guild.get_channel(notify_channel_id)
        if channel:
            await channel.send(f"{interaction.user.mention} أضاف {added} فصول مدفوعة في عمل `{العمل}`")

    total_user_amount = sum(item.get("total", 0) for item in records[user_id])
    threshold = SETTINGS.get("alert_threshold", 10.0)
    if total_user_amount >= threshold:
        try:
            await interaction.user.send(f"تنبيه: إجمالي شغلك وصل إلى {SETTINGS.get('currency', '$')}{total_user_amount:.2f}.")
        except:
            pass


# ═══════════════════════════════════════════════════════════════
# أمر /تسجيل_للغير — نفس الإيصال مع سطر «أضيف بواسطة»
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="تسجيل_للغير", description="تسجيل شغل لعضو معين (للمشرفين فقط)")
@app_commands.autocomplete(العمل=work_autocomplete, التخصصات=registration_specialty_autocomplete)
@app_commands.describe(
    عضو="العضو الذي تريد تسجيل الشغل له",
    العمل="اسم العمل (يجب أن يكون موجوداً في القائمة)",
    الفصول="نطاق الفصول مثل 1-5 أو 1,3,5",
    التخصصات="التخصصات مثل ترجمة كوري-تحرير",
    ملاحظات="ملاحظات اختيارية"
)
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def register_for_member(
    interaction: discord.Interaction,
    عضو: discord.Member,
    العمل: str,
    الفصول: str,
    التخصصات: str,
    ملاحظات: str = None
):
    avatar_url = interaction.client.user.display_avatar.url if interaction.client.user else None
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "تسجيل_للغير")
        await interaction.response.send_message(view=cards.permission_card(avatar_url), ephemeral=True)
        return
    if not channel_allowed(interaction):
        await interaction.response.send_message(view=cards.channel_card(SETTINGS.get("allowed_channels", []), avatar_url), ephemeral=True)
        return

    work, chapters_list, paid_chapters, free_count, filtered_types, error_card = await validate_registration(
        interaction, العمل, الفصول, التخصصات)
    if error_card is not None:
        await interaction.response.send_message(view=error_card, ephemeral=True)
        return

    records = await load_records()
    user_id = str(عضو.id)
    if user_id not in records:
        records[user_id] = []

    added_chapters_list = []
    added_types_list = []
    username = عضو.name
    duplicates_skipped = 0
    month_key = get_active_month_key()
    for idx, ch in enumerate(paid_chapters):
        work_type = filtered_types[idx]
        if is_duplicate(records, user_id, العمل, ch, work_type):
            duplicates_skipped += 1
            continue
        total = await get_specialty_price(العمل, work_type)
        records[user_id].append({
            "work_name": العمل,
            "chapter": ch,
            "work_type": work_type,
            "total": total,
            "notes": ملاحظات or "",
            "timestamp": datetime.utcnow().isoformat(),
            "month_key": month_key,
            "username": username,
            "added_by": str(interaction.user.id)
        })
        added_chapters_list.append(ch)
        added_types_list.append(work_type)

    added = len(added_chapters_list)
    if added == 0:
        await interaction.response.send_message(view=cards.error_card(
            "لم يُسجّل شيء جديد",
            ["لم يتم إضافة أي فصل جديد (جميع الفصول مكررة)."],
            avatar_url=avatar_url), ephemeral=True)
        return

    saved = await save_records(records)
    if not saved:
        await interaction.response.send_message(view=cards.error_card(
            "تعذر الحفظ",
            ["قاعدة البيانات غير متاحة الآن.",
             "لم تُسجل بياناتك — **لم يُفقد شيء** — أعد المحاولة بعد قليل."],
            avatar_url=avatar_url), ephemeral=True)
        return
    await update_stats()
    await upsert_member(عضو.id, عضو.name)

    if added_types_list and len(set(added_types_list)) == 1:
        total_amount = added * await get_specialty_price(العمل, added_types_list[0])
    else:
        total_amount = sum([await get_specialty_price(العمل, t) for t in added_types_list])

    receipt = build_receipt_card(
        requester=عضو,
        added_by=interaction.user,
        work_name=العمل,
        added_chapters=added_chapters_list,
        total_input_chapters=len(chapters_list),
        free_count=free_count,
        duplicates_skipped=duplicates_skipped,
        filtered_types=added_types_list,
        total_amount=total_amount,
        notes=ملاحظات,
        avatar_url=_user_avatar(عضو),
    )
    await interaction.response.send_message(view=receipt)

    notify_channel_id = SETTINGS.get("notify_channel_id")
    if notify_channel_id:
        channel = interaction.guild.get_channel(notify_channel_id)
        if channel:
            await channel.send(f"{interaction.user.mention} أضاف {added} فصول مدفوعة للعضو {عضو.mention} في عمل `{العمل}`")

    await log_audit("تسجيل_للغير", interaction.user.id, عضو.id,
                    f"أضاف {added} فصل لـ {العمل} (التخصصات: {','.join(filtered_types)})")

    try:
        await عضو.send(f"تم تسجيل {added} فصول مدفوعة لك في عمل `{العمل}` بواسطة {interaction.user.mention}.")
    except:
        pass


