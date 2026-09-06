import json
from io import BytesIO
import discord
from discord import app_commands
from discord.ext import commands
from state import bot
from helpers.core import (
    SETTINGS, log_unauthorized, log_audit, update_stats,
    load_settings, save_settings, load_records, save_records, load_works, save_works,
    entry_datetime, month_key_from_datetime, get_active_month_key,
)
from tasks.lifecycle import is_admin
from ui import cards


def _bot_avatar(interaction: discord.Interaction):
    return interaction.client.user.display_avatar.url if interaction.client.user else None


# ═══════════════════════════════════════════════════════════════
# /تحديد_قنوات — بطاقة نجاح بنمط ZEUS
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="تحديد_قنوات", description="تحديد القنوات المسموحة (قناتين كحد أقصى) - للإدارة فقط")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def set_allowed_channels_slash(interaction: discord.Interaction,
                                     channel1: str,
                                     channel2: str = None):
    avatar_url = _bot_avatar(interaction)
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "تحديد_قنوات")
        await interaction.response.send_message(view=cards.permission_card(avatar_url), ephemeral=True)
        return

    def resolve_channel(input_str: str):
        # Try to parse as mention <#123456>
        if input_str.startswith('<#') and input_str.endswith('>'):
            channel_id = int(input_str[2:-1])
            ch = bot.get_channel(channel_id)
            if ch:
                return ch.id   # تخزين المعرف بدلاً من الاسم
        # Try as numeric ID
        elif input_str.isdigit():
            ch = bot.get_channel(int(input_str))
            if ch:
                return ch.id   # تخزين المعرف
        # Otherwise treat as channel name (fallback)
        return input_str

    ch1_value = resolve_channel(channel1)
    channels = [ch1_value]
    if channel2:
        ch2_value = resolve_channel(channel2)
        channels.append(ch2_value)
    # إزالة التكرار والحفاظ على الحد الأقصى 2
    channels = list(dict.fromkeys(channels))[:2]
    SETTINGS["allowed_channels"] = channels
    await save_settings(SETTINGS)
    channels_str = ", ".join(
        f"<#{ch}>" if isinstance(ch, int) else f"#{ch}"
        for ch in SETTINGS["allowed_channels"]
    )
    await interaction.response.send_message(view=cards.success_card(
        "تم تحديث القنوات المسموحة",
        ["القنوات المسموحة الآن:", channels_str,
         "-# أوامر التسجيل لن تُقبل خارج هذه القنوات."],
        avatar_url=avatar_url), ephemeral=True)
    await log_audit("تحديد_قنوات", interaction.user.id, None, f"القنوات الجديدة: {channels_str}")


@bot.command(name="تحديد_قنوات")
@commands.has_permissions(manage_messages=True)
@commands.cooldown(1, 5, commands.BucketType.user)
async def set_allowed_channels_text(ctx, channel1: str, channel2: str = None):
    def extract_channel_name(input_str):
        # Try to resolve as mention or ID first (cross-server)
        if input_str.startswith('<#') and input_str.endswith('>'):
            channel_id = int(input_str[2:-1])
            ch = bot.get_channel(channel_id)
            if ch:
                return ch.id   # تخزين المعرف
        elif input_str.isdigit():
            ch = bot.get_channel(int(input_str))
            if ch:
                return ch.id   # تخزين المعرف
        # Fallback to local guild channel lookup by name or mention
        if input_str.startswith('<#') and input_str.endswith('>'):
            channel_id = int(input_str[2:-1])
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                return channel.id
        elif input_str.isdigit():
            channel = ctx.guild.get_channel(int(input_str))
            if channel:
                return channel.id
        else:
            for ch in ctx.guild.channels:
                if ch.name == input_str:
                    return ch.id   # تخزين المعرف
        return input_str
    ch1_value = extract_channel_name(channel1)
    channels = [ch1_value]
    if channel2:
        ch2_value = extract_channel_name(channel2)
        channels.append(ch2_value)
    channels = list(dict.fromkeys(channels))[:2]
    SETTINGS["allowed_channels"] = channels
    await save_settings(SETTINGS)
    channels_str = ", ".join(
        f"<#{ch}>" if isinstance(ch, int) else f"#{ch}"
        for ch in SETTINGS["allowed_channels"]
    )
    avatar_url = ctx.bot.user.display_avatar.url if ctx.bot.user else None
    await ctx.send(view=cards.success_card(
        "تم تحديث القنوات المسموحة",
        ["القنوات المسموحة الآن:", channels_str],
        avatar_url=avatar_url))
    await log_audit("تحديد_قنوات", ctx.author.id, None, f"القنوات الجديدة: {channels_str}")


# ═══════════════════════════════════════════════════════════════
# /رفع_البيانات — بطاقة استعادة بنمط ZEUS (قائمة مراحل ✓)
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="رفع_البيانات", description="رفع ملف JSON لاستعادة السجلات والأعمال إلى MongoDB")
@app_commands.checks.cooldown(1, 10, key=lambda i: (i.user.id, i.command.qualified_name))
async def upload_records(interaction: discord.Interaction, file: discord.Attachment):
    avatar_url = _bot_avatar(interaction)
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "رفع_البيانات")
        await interaction.response.send_message(view=cards.permission_card(avatar_url), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    if not file.filename.endswith('.json'):
        await interaction.followup.send(view=cards.error_card(
            "الملف غير مدعوم",
            ["الملف يجب أن يكون بصيغة JSON."],
            avatar_url=avatar_url), ephemeral=True)
        return
    try:
        content = await file.read()
        data = json.loads(content.decode('utf-8'))

        # Support both old format (plain records dict) and new format with "records" and optional "works"
        if isinstance(data, dict):
            records_data = data.get("records", data)  # fallback to whole dict
            works_data = data.get("works", None)
        else:
            await interaction.followup.send(view=cards.error_card(
                "الملف غير صالح",
                ["محتوى الملف غير مفهوم — ارفع ملف نسخة احتياطية صالح."],
                avatar_url=avatar_url), ephemeral=True)
            return

        # Update records — مع ختم شهر كل سجل من تاريخه ليعمل فورًا مع نظام الشهور
        if not isinstance(records_data, dict):
            await interaction.followup.send(view=cards.error_card(
                "قسم records غير صالح",
                ["قسم السجلات في الملف غير صالح."],
                avatar_url=avatar_url), ephemeral=True)
            return
        for user_entries in records_data.values():
            if isinstance(user_entries, list):
                for entry in user_entries:
                    if isinstance(entry, dict) and not entry.get("month_key"):
                        dt = entry_datetime(entry)
                        entry["month_key"] = month_key_from_datetime(dt) if dt else get_active_month_key()
        from database import collection
        await collection.update_one({"_id": "records"}, {"$set": {"data": records_data}}, upsert=True)
        total_users = len(records_data)
        total_entries = sum(len(entries) for entries in records_data.values() if isinstance(entries, list))

        # --- NEW: Auto-extract works from records ---
        works_from_records = set()
        for user_entries in records_data.values():
            if isinstance(user_entries, list):
                for entry in user_entries:
                    if isinstance(entry, dict) and "work_name" in entry:
                        works_from_records.add(entry["work_name"])

        if works_from_records:
            current_works = await load_works()
            existing_names = {w["name"] for w in current_works}
            added_works_count = 0
            for name in works_from_records:
                if name not in existing_names:
                    current_works.append({"name": name, "paid_start": None, "active": True})
                    existing_names.add(name)
                    added_works_count += 1
            if added_works_count > 0:
                await save_works(current_works)
        else:
            added_works_count = 0
        # --- End of auto-extract ---

        # Update works from file if present (overwrites if the user provided a "works" section)
        if works_data is not None:
            if isinstance(works_data, list):
                await save_works(works_data)
                added_works_count = len(works_data)  # override count with explicit works data
            else:
                await interaction.followup.send(view=cards.error_card(
                    "قسم works غير صالح",
                    ["تم تحديث السجلات لكن قسم works غير صالح (تم تجاهله)."],
                    avatar_url=avatar_url), ephemeral=True)
                await log_audit("رفع_البيانات", interaction.user.id, None,
                                f"تم رفع {total_entries} سجل (works غير محدثة)")
                await update_stats()
                return

        await log_audit("رفع_البيانات", interaction.user.id, None,
                        f"تم رفع {total_entries} سجل" + (f" و {added_works_count} عمل جديد" if added_works_count else ""))
        await update_stats()

        # بطاقة النجاح — قائمة مراحل ✓
        children: list = [
            cards.header(["## تم استعادة البيانات", "<@" + str(interaction.user.id) + ">"], avatar_url),
            cards.sep(2),
        ]
        checklist = [
            f"✓ قراءة الملف — {file.filename}",
            f"✓ استعادة السجلات — {total_entries} سجل لـ {total_users} عضو",
        ]
        if added_works_count:
            checklist.append(f"✓ استخراج الأعمال — {added_works_count} عمل")
        if works_data is not None and isinstance(works_data, list):
            checklist.append(f"✓ تحديث الأعمال من الملف — {len(works_data)} عمل")
        children.append(cards.text("\n".join(checklist)))
        children += [cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
        await interaction.followup.send(view=cards.Card(cards.ACCENT_GREEN, *children), ephemeral=True)
    except json.JSONDecodeError:
        await interaction.followup.send(view=cards.error_card(
            "الملف ليس بصيغة JSON صحيحة",
            ["تحقق من الملف ثم أعد الرفع."],
            avatar_url=avatar_url), ephemeral=True)
    except Exception as e:
        print(f"[ERROR] Slash command restore failed: {e}")
        await interaction.followup.send(view=cards.error_card(
            "فشل الرفع",
            [f"حدث خطأ: {str(e)[:500]}"],
            avatar_url=avatar_url), ephemeral=True)
