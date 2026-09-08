# ═══════════════════════════════════════════════════════════════
# 🛡️ الحارس الموحد لكل عروض Components V2:
#   قبل هذا الحارس: أي خطأ داخل callback لقائمة منسدلة أو زر كان
#   يُبتلع بصمت في BaseView.on_error (يسجل فقط) → التفاعل يبقى
#   "يفكر" للأبد ولا يعرف العضو سبب الصمت.
#   الآن: كل خطأ يُجاب ببطاقة واضحة فورًا (أو تعديل للرسالة)،
#   وأخطاء قاعدة البيانات تحصل على بطاقتها الخاصة بدل الصمت.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import discord
from discord import ui

from database import DatabaseUnavailableError


class SafeLayoutView(ui.LayoutView):
    """قاعدة كل العروض: يجيب التفاعل دائمًا — حتى عند الفشل."""

    def _fallback_user(self, interaction: discord.Interaction):
        """أفضل محاولة لصورة العضو/البوت لرأس البطاقة."""
        try:
            if interaction.user is not None:
                return interaction.user.display_avatar.url
        except Exception:
            pass
        try:
            return interaction.client.user.display_avatar.url
        except Exception:
            return None

    async def _answer_failure(self, interaction: discord.Interaction, error: Exception):
        from ui import cards
        avatar = self._fallback_user(interaction)
        if isinstance(error, DatabaseUnavailableError):
            view = cards.error_card(
                "قاعدة البيانات غير متاحة",
                ["تعذر الوصول إلى قاعدة البيانات أثناء تنفيذ هذه الخطوة.",
                 "بياناتك المحفوظة **آمنة ولم تُمس** — أعد المحاولة بعد قليل.",
                 "للتشخيص الدقيق استخدم /تشخيص."],
                avatar_url=avatar)
        else:
            view = cards.error_card(
                "حدث خطأ غير متوقع",
                [f"`{str(error)[:300]}`"],
                avatar_url=avatar)
        try:
            if interaction.response.is_done():
                if interaction.message is not None:
                    await interaction.message.edit(view=view)
                else:
                    await interaction.followup.send(view=view, ephemeral=True)
            else:
                await interaction.response.send_message(view=view, ephemeral=True)
        except Exception:
            try:
                await interaction.followup.send(view=view, ephemeral=True)
            except Exception:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item, /) -> None:
        import traceback
        print(f"[VIEW ERROR] {type(error).__name__}: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        await self._answer_failure(interaction, error)

    async def on_timeout(self) -> None:
        # مهلة العرض تنتهي بهدوء — الجلسات التي تحتاج تنظيفًا تدير مهلتها بنفسها.
        return
