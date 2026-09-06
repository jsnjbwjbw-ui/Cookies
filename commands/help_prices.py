from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from state import bot
from helpers.core import SETTINGS
from helpers.core import save_settings, rebuild_prices, map_type
from tasks.lifecycle import is_admin, specialty_autocomplete
from ui import cards


def bot_avatar(interaction: discord.Interaction):
    return interaction.client.user.display_avatar.url if interaction.client.user else None


# ═══════════════════════════════════════════════════════════════
# 📖 بطاقة المساعدة — نفس بنية بطاقة /مساعدة في بوت السحب بالضبط:
#   حاوية ذهبية + رأس «## 📖 ZEUS» بصورة البوت + سطر تعريف،
#   ثم قسم «### 🔹 /الأمر» لكل أمر مفصول بفواصل، ثم -# ZEUS.
# ═══════════════════════════════════════════════════════════════
def build_help_card(avatar_url: str | None, user_mention: str) -> cards.Card:
    children: list = [
        cards.header(
            [
                "## 📖 ZEUS",
                f"أهلاً {user_mention} — بوت إدارة فلوس فريق كوكيز: سجّل فصولك، وتابع مستحقاتك، "
                "ويحسب البوت كل شيء بدقة حتى يوم الدفع.",
            ],
            avatar_url,
        ),
        cards.sep(2),
    ]

    def command_block(title: str, body: str):
        children.append(cards.text(f"### 🔹 {title}\n{body}"))
        children.append(cards.sep())

    # ── أوامر الأعضاء ──
    command_block("/تسجيل", "تسجيل فصول منجزة واستلام إيصال جاهز بالحساب.\n"
                  "**1.** اختر العمل من القائمة.\n**2.** اكتب الفصول مثل `1-5`.\n"
                  "**3.** حدد التخصصات مثل `ترجمة كوري-تحرير` ويصلك الإيصال فورًا.")
    command_block("/أعمالي", "لوحتك الشخصية: أعمالك مجمعة مع المكافآت والخصومات والصافي النهائي، "
                  "واختيار أي عمل يفتح تفاصيل فصوله.")
    command_block("/شغل", "عرض شغل أي عضو مجمّع — اذكر العضو أو اتركه فارغًا لك.")
    command_block("/ملخص_شهري", "ملخص شغلك للشهر الحالي: عدد الفصول، المبلغ المستحق، وتفصيل الأعمال.")
    command_block("/تقريري", "تقرير أسبوعي خاص بك: مهام آخر 7 أيام ومجموعها.")
    command_block("/تعديل", "تعديل آخر سجل قمت بإضافته مباشرة في حال حدوث خطأ.")
    command_block("/اسعار", "عرض قائمة أسعار التخصصات المعتمدة، مع التخصيصات الخاصة لكل عمل.")
    command_block("/الأعمال", "عرض قائمة الأعمال المعتمدة ومساهمين فيها — اختر عملاً لفتح أعضائه وفصولهم.")
    command_block("/احصائيات", "لوحة إحصائيات تفاعلية: نظرة عامة، التخصصات، الزمني، والأفضل.")
    command_block("/توب", "ترتيب الأعضاء حسب المبلغ أو عدد الفصول أو داخل تخصص محدد.")
    command_block("/مساعدة", "عرض هذا الدليل.")

    # ── أوامر الإدارة ──
    children.append(cards.text(
        "### 🔹 أوامر الإدارة\n"
        "• `/تسجيل_للغير` — تسجيل شغل لعضو معين.\n"
        "• `/تعديل_سعر` و `/تحديث_أسعار` — تعديل سعر تخصص وتطبيقه بأثر رجعي.\n"
        "• `/اضافة_تخصص` • `/حذف_تخصص` • `/تفعيل_تخصص` • `/تعطيل_تخصص` — إدارة التخصصات.\n"
        "• `/اضافة_عمل` • `/حذف_عمل` • `/تعديل_عمل` • `/عرض_الاعمال` — إدارة الأعمال.\n"
        "• `/عزل_عمل` و `/استرجاع_عمل` — تأجيل احتساب عمل كامل أو إعادته دون حذف سجلاته.\n"
        "• `/تخصيص_سعر_عمل` • `/الغاء_تخصيص_عمل` • `/عرض_تخصيصات_عمل` — أسعار خاصة بعمل محدد.\n"
        "• `/نقل_تخصص_للخاص` و `/نقل_تخصص_للعام` — نقل تخصص بين العامة وتخصيصات العمل.\n"
        "• `/مكافأة` • `/خصم` • `/حذف_مكافأة_خصم` — نظام المكافآت والخصومات.\n"
        "• `/حذف` • `/حذف_الكل` • `/حذف_كل_الأعمال` — حذف السجلات والأعمال.\n"
        "• `/الأعضاء` • `/اعضاء_تخصص` • `/تقرير_دفع` — المستحقات وتقارير الدفع مع تصدير Excel.\n"
        "• `/لوحة_التحكم` و `/سجل` — مركز الإدارة وسجل العمليات.\n"
        "• `/اعدادات` • `/تحديد_قنوات` • `/تحديد_موعد_الدفع` — إعدادات السيرفر.\n"
        "• `/رفع_البيانات` و `/تصدير` — النسخ والاستعادة."
    ))
    children.append(cards.sep())
    children.append(cards.text(
        "سلسلة التسجيل: فحص العمل ← فلترة الفصول المدفوعة ← تسجيل الفصول ← حساب المستحق ← إيصال جاهز."
    ))
    children.append(cards.sep())
    children.append(cards.text("-# الأمر /تسجيل متاح في القنوات المحددة من /تحديد_قنوات، وأوامر الإدارة لمن يملك صلاحية إدارة الرسائل فأعلى."))
    children.append(cards.sep())
    children.append(cards.text(f"-# {cards.BOT_SIGNATURE}"))

    return cards.Card(cards.ACCENT_GOLD, *children)


async def _send_help(interaction: discord.Interaction):
    await interaction.response.send_message(
        view=build_help_card(bot_avatar(interaction), interaction.user.mention))


@bot.tree.command(name="مساعدة", description="شرح الأوامر وطريقة الاستخدام")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def help_slash(interaction: discord.Interaction):
    await _send_help(interaction)


@bot.tree.command(name="اوامر", description="عرض دليل الأوامر للبوت")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def help_slash_alias(interaction: discord.Interaction):
    await _send_help(interaction)


# ═══════════════════════════════════════════════════════════════
# 🏷️ /اسعار — بطاقة الأسعار بنمط قائمة المواقع في بوت السحب
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="اسعار", description="عرض أسعار التخصصات المعتمدة")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def prices_slash(interaction: discord.Interaction):
    avatar_url = bot_avatar(interaction)
    currency = SETTINGS.get('currency', '$') or '$'
    children: list = [
        cards.header(["## 🏷️ أسعار ZEUS", f"**{len(PRICES)}** تخصصات متاحة بسعر الفصل الواحد."], avatar_url),
        cards.sep(2),
    ]
    if PRICES:
        bullets = "\n".join(f"• **{spec.replace('_', ' ').title()}** — {currency}{price:.2f}"
                            for spec, price in sorted(PRICES.items(), key=lambda kv: -kv[1]))
        children.append(cards.text(bullets))
    else:
        children.append(cards.text("لا توجد تخصصات مفعّلة بعد — يضيفها المشرفون من /اضافة_تخصص."))

    # التخصيصات الخاصة بالأعمال
    from helpers.core import load_works
    works = await load_works()
    custom_groups = [(w["name"], w.get("custom_prices", {})) for w in works if w.get("custom_prices")]
    for work_name, custom in custom_groups[:5]:
        children.append(cards.sep(2))
        custom_bullets = "\n".join(f"• **{spec.replace('_', ' ').title()}** — {currency}{float(price):.2f}"
                                   for spec, price in custom.items())
        children.append(cards.text(f"**تخصيصات عمل «{work_name}»**\n{custom_bullets}"))
    if len(custom_groups) > 5:
        children.append(cards.sep())
        children.append(cards.text(f"-# و{len(custom_groups) - 5} أعمال أخرى لها تخصيصات سعرية…"))

    children += [cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
    await interaction.response.send_message(view=cards.Card(cards.ACCENT_GOLD, *children))


# ═══════════════════════════════════════════════════════════════
# /تعديل_سعر — بطاقة نجاح بنمط ZEUS
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="تعديل_سعر", description="تعديل سعر تخصص معين (للمشرفين فقط)")
@app_commands.autocomplete(التخصص=specialty_autocomplete)
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def edit_price_slash(interaction: discord.Interaction, التخصص: str, السعر: float):
    avatar_url = bot_avatar(interaction)
    if not is_admin(interaction):
        await interaction.response.send_message(view=cards.permission_card(avatar_url), ephemeral=True)
        return
    norm_type = map_type(التخصص)
    if norm_type not in SETTINGS.get("specialties", {}):
        await interaction.response.send_message(view=cards.error_card(
            "❌ التخصص غير موجود",
            [f"التخصص `{التخصص}` غير موجود في القائمة."],
            avatar_url=avatar_url), ephemeral=True)
        return
    SETTINGS["specialties"][norm_type]["price"] = السعر
    SETTINGS["specialties"][norm_type]["last_modified"] = datetime.utcnow().isoformat()
    await save_settings(SETTINGS)
    rebuild_prices()
    currency = SETTINGS.get('currency', '$') or '$'
    await interaction.response.send_message(view=cards.success_card(
        "✅ تم تحديث السعر",
        [f"التخصص **{norm_type.replace('_', ' ').title()}** — السعر الجديد: **{currency}{السعر:.2f}** لكل فصل.",
         "-# تذكير: لا تنس استخدام الأمر `/تحديث_أسعار` لتطبيق السعر الجديد على السجلات القديمة إذا كنت ترغب في ذلك."],
        avatar_url=avatar_url), ephemeral=True)
