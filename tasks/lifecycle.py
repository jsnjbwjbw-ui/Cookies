import json
from io import BytesIO
from datetime import datetime, timedelta
from typing import List

import discord
from discord.ext import commands, tasks
from discord import app_commands

from state import bot
from database import mongo_client
from helpers.core import *  # noqa: F401 — يشمل is_admin الموحدة وتُعاد تصديرها لكل الملفات
from ui import cards

BOT_DISPLAY_NAME = "Cookies Tracker"   # الاسم الظاهر للجميع (يدعم الفراغات)
BOT_USERNAME = "Cookies_Tracker"       # معرف الحساب (بدون فراغات حسب قواعد ديسكورد)
BOT_PRESENCE = "Cookies Tracker | /مساعدة"


async def _apply_bot_identity():
    """فرض هوية البوت: الاسم الظاهر + المعرف + الحالة — مرة واحدة عند الإقلاع."""
    # 1) الاسم الظاهر (global_name) — discord.py لا يعرضه في edit لذا نستخدم API مباشر
    try:
        if getattr(bot.user, "global_name", None) != BOT_DISPLAY_NAME:
            route = discord.http.Route("PATCH", "/users/@me")
            await bot.http.request(route, json={"global_name": BOT_DISPLAY_NAME})
            try:
                bot.user.global_name = BOT_DISPLAY_NAME
            except Exception:
                pass
            print(f"[LOG] Bot display name set to {BOT_DISPLAY_NAME}")
    except Exception as e:
        print(f"[WARNING] Could not set display name: {e}")
    # 2) المعرف (username) — فقط إن كان قديمًا (مثل ZEUS)
    try:
        if bot.user and bot.user.name != BOT_USERNAME:
            await bot.user.edit(username=BOT_USERNAME)
            print(f"[LOG] Bot username set to {BOT_USERNAME}")
    except Exception as e:
        print(f"[WARNING] Could not set username (قد يكون بسبب حد تغيير الأسماء في ديسكورد): {e}")


async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CheckFailure):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("ما عندك صلاحية تستخدم هذا الأمر.")
        return
    await ctx.send(f"صار خطأ: `{error}`")


@bot.event
async def on_ready():
    print(f"[LOG] Logged in as {bot.user}")
    # ── هوية Cookies Tracker: الاسم الظاهر + المعرف + الحالة ──
    await _apply_bot_identity()
    try:
        await bot.change_presence(
            status=discord.Status.online,
            activity=discord.Activity(type=discord.ActivityType.watching, name=BOT_PRESENCE),
        )
    except Exception as e:
        print(f"[WARNING] Could not set presence: {e}")

    loaded_settings = await load_settings()
    SETTINGS.clear()
    SETTINGS.update(loaded_settings)
    rebuild_prices()
    print(f"[LOG] Settings loaded: allowed_channels={SETTINGS.get('allowed_channels')}, "
          f"currency={SETTINGS.get('currency')}")
    try:
        await mongo_client.admin.command('ping')
        print("[LOG] MongoDB connection successful!")
    except Exception as e:
        print(f"[ERROR] MongoDB connection failed: {e}")
    await bot.tree.sync()
    print("[LOG] Slash commands synced")
    await update_stats()
    daily_backup.start()
    update_stats_task.start()
    payment_reminder_task.start()


@bot.check
async def only_allowed_channel(ctx):
    """نفس منطق channel_allowed: المعرف الرقمي أو الاسم — لا مقارنة بالاسم وحده."""
    if ctx.author.bot:
        return False
    allowed = SETTINGS.get("allowed_channels", [])
    if getattr(ctx.channel, "id", None) in allowed:
        return True
    if getattr(ctx.channel, "name", None) in allowed:
        return True
    channels_str = "، ".join(
        f"<#{ch}>" if isinstance(ch, int) else f"#{ch}" for ch in allowed
    )
    await ctx.send(f"استخدم أوامر البوت فقط في أحد الرومات التالية:\n{channels_str}")
    return False


# is_admin تأتي من helpers.core عبر الاستيراد أعلاه (administrator أو manage_messages)
# لتوحيد الصلاحية في كل أوامر البوت بدون تضارب.


@tasks.loop(hours=24)
async def daily_backup():
    # 🔁 قم بتغيير هذا المعرف إلى معرف القناة في السيرفر الآخر حيث تريد إرسال النسخ الاحتياطية
    REMOTE_BACKUP_CHANNEL_ID = 1351312425818914836  # ⚠️ استبدل هذا الرقم بالمعرف الحقيقي للقناة

    channel = bot.get_channel(REMOTE_BACKUP_CHANNEL_ID)
    if not channel:
        print(f"[WARNING] Remote backup channel {REMOTE_BACKUP_CHANNEL_ID} not found. Backup not sent.")
        return

    records = await load_records()
    data = json.dumps(records, ensure_ascii=False, indent=2)
    file = discord.File(BytesIO(data.encode('utf-8')), filename=f"backup_{datetime.utcnow().date()}.json")
    await channel.send(f"نسخة احتياطية يومية — {datetime.utcnow().date()}", file=file)


@tasks.loop(hours=1)
async def update_stats_task():
    await update_stats()


@tasks.loop(minutes=10)
async def payment_reminder_task():
    await check_payment_reminder()


async def check_payment_reminder():
    """Check if it's time to send payment reminders."""
    payment_day = SETTINGS.get("payment_day")
    if not payment_day:
        return
    now = datetime.utcnow()
    payment_hour = SETTINGS.get("payment_hour", 0)
    # Check if today is the payment day
    today = now.date()
    payment_date = today.replace(day=min(payment_day, 28))  # avoid month issues
    if payment_day > 28:
        payment_date = today.replace(day=28)  # safe fallback

    # 24 hours before reminder
    reminder_date = payment_date - timedelta(days=1)
    if now.date() == reminder_date and now.hour >= payment_hour and not SETTINGS.get("payment_reminder_24h_sent"):
        await send_payment_reminder(24)
        SETTINGS["payment_reminder_24h_sent"] = True
        await save_settings(SETTINGS)
    # Payment day reminder
    elif now.date() == payment_date and now.hour >= payment_hour and not SETTINGS.get("payment_day_sent"):
        await send_payment_reminder(0)
        SETTINGS["payment_day_sent"] = True
        await save_settings(SETTINGS)
    # Reset flags when day passes
    elif now.date() > payment_date:
        SETTINGS["payment_reminder_24h_sent"] = False
        SETTINGS["payment_day_sent"] = False
        await save_settings(SETTINGS)


async def send_payment_reminder(hours_before):
    """Send a payment reminder — بطاقة Components V2 بنمط ZEUS."""
    notify_channel_id = SETTINGS.get("notify_channel_id") or SETTINGS.get("daily_backup_channel_id")
    if not notify_channel_id:
        return
    channel = bot.get_channel(notify_channel_id)
    if not channel:
        return
    # Gather monthly totals
    records = await load_visible_records()
    month_start = datetime.utcnow().replace(day=1)
    totals = {}
    for user_id, entries in records.items():
        user_total = 0
        for e in entries:
            try:
                entry_date = datetime.fromisoformat(e["timestamp"])
                if entry_date >= month_start:
                    user_total += e.get("total", 0)
            except:
                pass
        if user_total != 0:
            totals[user_id] = user_total
    total_all = sum(totals.values())
    currency = SETTINGS.get('currency', '$') or '$'
    avatar_url = bot.user.display_avatar.url if bot.user else None

    title = "تذكير بموعد الدفع" if hours_before == 24 else "اليوم هو موعد الدفع الشهري"
    intro = ("تبقى 24 ساعة على موعد الدفع الشهري." if hours_before == 24
             else "اليوم هو موعد الدفع الشهري.")

    body_lines = [
        intro,
        f"**💰 إجمالي المبلغ المستحق:** {currency}{total_all:,.2f}",
    ]
    if totals:
        top5 = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:5]
        top_str = "\n".join(f"• <@{uid}> — {currency}{amt:,.2f}" for uid, amt in top5)
        body_lines.append(f"**أعلى 5 مستحقات**\n{top_str}")

    await channel.send(view=cards.simple_card(cards.ACCENT_GOLD, title, body_lines, avatar_url=avatar_url))


# ----------------------------------------------------------------------
# Autocomplete helpers
# ----------------------------------------------------------------------
async def work_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    works = await load_works()
    choices = []
    for w in works:
        if current.lower() in w["name"].lower():
            choices.append(app_commands.Choice(name=w["name"][:100], value=w["name"]))
    return choices[:25]


async def registration_specialty_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    """
    تُستخدم فقط في أوامر التسجيل (/تسجيل و /تسجيل_للغير).
    إذا كان العمل المختار يمتلك تخصيصات خاصة، تُظهرها فقط.
    وإلا تُظهر التخصصات العامة.
    """
    work_name = None
    try:
        work_name = interaction.namespace.العمل
    except AttributeError:
        pass

    if work_name:
        work = await get_work(work_name)
        if work and "custom_prices" in work and isinstance(work["custom_prices"], dict):
            choices = []
            for spec in work["custom_prices"].keys():
                display_name = spec.replace('_', ' ').title()
                if current.lower() in display_name.lower():
                    choices.append(app_commands.Choice(name=display_name[:100], value=spec))
            return choices[:25]

    # Fallback to global specialties
    choices = []
    for name in PRICES.keys():
        display_name = name.replace('_', ' ').title()
        if current.lower() in display_name.lower():
            choices.append(app_commands.Choice(name=display_name[:100], value=name))
    return choices[:25]


async def specialty_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    """
    تُستخدم في أوامر الإدارة.
    تُظهر جميع التخصصات العامة + أي تخصص خاص من أي عمل غير موجود في العامة،
    مع ملاحظة " (خاص لعمل X)" في الاسم.
    """
    choices = []
    # 1. التخصصات العامة (من PRICES)
    for spec in PRICES.keys():
        display = spec.replace('_', ' ').title()
        if current.lower() in display.lower():
            choices.append(app_commands.Choice(name=display[:100], value=spec))

    # 2. التخصصات الخاصة من أي عمل، بشرط أن لا تكون موجودة أصلاً في العامة
    works = await load_works()
    for w in works:
        custom = w.get("custom_prices", {})
        for spec, price in custom.items():
            if spec not in PRICES:  # ليس لها مقابل عام، نُظهرها مع ملاحظة
                display = spec.replace('_', ' ').title() + f" (خاص لعمل {w['name']})"
                if current.lower() in display.lower():
                    choices.append(app_commands.Choice(name=display[:100], value=spec))
    return choices[:25]


async def custom_setup():
    bot.add_listener(on_command_error, "on_command_error")
