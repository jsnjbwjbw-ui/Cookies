# ═══════════════════════════════════════════════════════════════
# 🩺 /تشخيص — فحص فوري ومصنّف لقاعدة البيانات:
#   يقيس ping حقيقي ويصنّف أي فشل (صيغة رابط / DNS / بيانات دخول /
#   مهلة-حجب / TLS) ويقول الحل المضبوط — بدل التخمين الأعمى.
# ═══════════════════════════════════════════════════════════════
import discord
from discord import app_commands
from state import bot
from helpers.core import SETTINGS, is_admin, log_audit
from database import diagnose_db, db_ready, MONGODB_DB_NAME
from ui import cards


def _bot_avatar() -> str | None:
    return bot.user.display_avatar.url if bot.user else None


@bot.tree.command(name="تشخيص",
                  description="فحص اتصال قاعدة البيانات مع تحديد السبب والحل (للمشرفين)")
@app_commands.checks.cooldown(1, 10, key=lambda i: (i.user.id, i.command.qualified_name))
async def diagnostics(interaction: discord.Interaction):
    avatar = _bot_avatar()
    if not is_admin(interaction):
        await interaction.response.send_message(view=cards.permission_card(avatar), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    d = await diagnose_db()

    if d["ok"]:
        lines = [
            "**النتيجة:** الاتصال سليم تمامًا.",
            f"**زمن الاستجابة:** {d['latency_ms']}ms",
            f"**قاعدة البيانات:** `{d['db_name']}`",
            f"**الرابط المستخدم:** `{d['uri_masked']}`",
            "**ملاحظة:** إذا استمرت الأوامر بطيئة بعد هذا الفحص فالمشكلة في الشبكة لحظية — "
            "أعد المحاولة، وإن تكررت راقب /تشخيص بعدها مباشرة.",
        ]
        await interaction.followup.send(view=cards.success_card(
            "قاعدة البيانات سليمة", lines, avatar_url=avatar), ephemeral=True)
        return

    category_names = {
        "config": "صيغة الرابط",
        "dns": "اسم المضيف (DNS)",
        "auth": "بيانات الدخول",
        "timeout": "حجب / مهلة اتصال",
        "tls": "أمان الاتصال (TLS)",
        "unknown": "غير مصنّف",
    }
    lines = [
        f"**نوع المشكلة:** {category_names.get(d['category'], d['category'])}",
        f"**التفصيل:** {d['problem']}",
        f"**الحل:** {d['fix']}",
        "────────────────────",
        f"**الرابط المستخدم:** `{d['uri_masked']}`",
        f"**اسم قاعدة البيانات:** `{d['db_name']}`",
        f"**زمن المحاولة:** {d['latency_ms']}ms",
        f"**حالة البوت الداخلية:** {'سليمة' if db_ready else 'منقطعة'}",
        "────────────────────",
        "**تذكير مهم:** بياناتك لا تُمسّ أثناء الانقطاع — البوت يرفض الكتابة "
        "حمايةً لها، وتعود كل الأوامر للعمل تلقائيًا فور عودة الاتصال.",
    ]
    await interaction.followup.send(view=cards.error_card(
        "قاعدة البيانات غير متاحة", lines, avatar_url=avatar), ephemeral=True)
    await log_audit("تشخيص_قاعدة_البيانات", interaction.user.id, None,
                    f"category={d['category']} ok={d['ok']}")
