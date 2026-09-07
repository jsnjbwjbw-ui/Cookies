"""مركز التخصصات — أمر واحد يجمع كل شيء عن التخصصات بأسلوب لوحة التحكم:
- نظرة عامة: عدد التخصصات العامة والمفعلة والمعطلة والتخصيصات الخاصة.
- أزرار تنفّذ: الأسعار العامة، المعطلة، تخصيصات الأعمال، وقائمة إدارة أي تخصص.
- كل الأزرار رمادية، وكل قسم له زر رجوع، وكل رقم في سطر مستقل، بلا إيموجي.
الإضافة والحذف والنقل تبقى من أوامرها (تحتاج معاملات كتابة).
"""
from collections import defaultdict
from datetime import datetime
import discord
from discord import app_commands, ui
from state import bot
from helpers.core import (
    SETTINGS, PRICES, is_admin, log_unauthorized, log_audit,
    save_settings, rebuild_prices, load_records, load_works,
    get_active_month_key, DatabaseUnavailableError,
)
from ui import cards


def _bot_avatar() -> str | None:
    return bot.user.display_avatar.url if bot.user else None


async def _resolve(parent):
    """حل زر الرجوع: view جاهز أو دالة متزامنة/غير متزامنة."""
    if callable(parent):
        result = parent()
        if hasattr(result, "__await__"):
            result = await result
        return result
    return parent


async def specialty_usage_counts() -> tuple[dict, dict]:
    """عدد سجلات كل تخصص: (كل الشهور، الشهر النشط فقط)."""
    all_records = await load_records()
    active_key = get_active_month_key()
    all_counts: dict = defaultdict(int)
    month_counts: dict = defaultdict(int)
    for entries in all_records.values():
        for e in entries:
            t = e.get("work_type")
            if not t or t in ("مكافأة", "خصم"):
                continue
            all_counts[t] += 1
            if e.get("month_key") == active_key:
                month_counts[t] += 1
    return dict(all_counts), dict(month_counts)


# ═══════════════════════════════════════════════════════════════
# لوحة التخصصات الرئيسية
# ═══════════════════════════════════════════════════════════════
class SpecialtiesHubView(ui.LayoutView):
    def __init__(self, back=None):
        super().__init__(timeout=900.0)
        self.back = back

    @classmethod
    async def create(cls, back=None):
        self = cls(back)
        await self.rebuild_async()
        return self

    async def rebuild_async(self):
        self.clear_items()
        children = await self.build_children()
        self.add_item(cards.container(cards.ACCENT_GOLD, *children))

    async def _back_cb(self, interaction: discord.Interaction):
        parent = await _resolve(self.back)
        if parent is None:
            await interaction.response.defer()
            return
        await interaction.response.edit_message(view=parent)

    async def build_children(self) -> list:
        currency = SETTINGS.get('currency', '$') or '$'
        specialties = SETTINGS.get("specialties", {})
        active_specs = [s for s, v in specialties.items() if v.get("active", True)]
        disabled_specs = [s for s, v in specialties.items() if not v.get("active", True)]
        works = await load_works()
        custom_works = [w for w in works if w.get("custom_prices")]
        custom_total = sum(len(w.get("custom_prices", {})) for w in custom_works)

        children: list = [
            cards.header(["## مركز التخصصات",
                          "كل ما يخص التخصصات والأسعار في لوحة واحدة — الأزرار تنفّذ مباشرة."],
                         _bot_avatar()),
            cards.sep(2),
            cards.text(
                "### النظرة العامة\n"
                f"**التخصصات العامة:** {len(specialties)}\n"
                f"**المفعّلة:** {len(active_specs)}\n"
                f"**المعطّلة:** {len(disabled_specs)}\n"
                f"**أعمال لها أسعار خاصة:** {len(custom_works)}\n"
                f"**التخصيصات السعرية:** {custom_total}\n"
                f"**العملة:** {currency}"
            ),
            cards.sep(),
            cards.row(
                cards.secondary_btn("الأسعار العامة", self._open_prices),
                cards.secondary_btn("التخصصات المعطلة", self._open_disabled),
                cards.secondary_btn("تخصيصات الأعمال", self._open_custom),
            ),
        ]

        # قائمة إدارة أي تخصص
        options = []
        for spec in sorted(specialties.keys()):
            v = specialties[spec]
            status = "نشط" if v.get("active", True) else "معطل"
            options.append(discord.SelectOption(
                label=cards.clamp(spec.replace('_', ' ').title(), 100), value=spec,
                description=cards.clamp(f"{currency}{v.get('price', 0):.2f} لكل فصل • {status}", 100),
                emoji="🛠️"))
        if options:
            children.append(cards.sep())
            children.append(cards.text("-# اختر أي تخصص لفتح بطاقته: السعر والحالة والاستخدام وتفعيله أو تعطيله."))
            children.append(cards.make_select("إدارة تخصص...", options, self._spec_picked))
        else:
            children.append(cards.sep())
            children.append(cards.text("لا توجد تخصصات بعد — ابدأ بـ /اضافة_تخصص."))

        children += [
            cards.sep(),
            cards.text("-# الإضافة والحذف والنقل من أوامرها: /اضافة_تخصص • /حذف_تخصص • /نقل_تخصص_للخاص • /نقل_تخصص_للعام"),
        ]
        if self.back is not None:
            children += [cards.sep(), cards.row(cards.secondary_btn("عودة إلى لوحة التحكم", self._back_cb, emoji="↩"))]
        children += [cards.sep(), cards.text(f"-# {cards.BOT_SIGNATURE}")]
        return children

    # ── الأسعار العامة ──
    async def _open_prices(self, interaction: discord.Interaction):
        await interaction.response.defer()
        currency = SETTINGS.get('currency', '$') or '$'
        if PRICES:
            max_price = max(PRICES.values()) or 1
            body = "\n".join(
                f"• **{spec.replace('_', ' ').title()}** — {cards.progress_bar(price, max_price)} {currency}{price:.2f}"
                for spec, price in sorted(PRICES.items(), key=lambda kv: -kv[1]))
        else:
            body = "لا توجد تخصصات مفعّلة بعد — يضيفها المشرفون من /اضافة_تخصص."
        children: list = [
            cards.header(["## الأسعار العامة", f"سعر الفصل الواحد لكل تخصص معتمد — **{len(PRICES)}** تخصص."],
                         _bot_avatar()),
            cards.sep(2),
            cards.text(body),
            cards.sep(),
            cards.row(cards.secondary_btn("عودة إلى مركز التخصصات", self._back_cb, emoji="↩")),
            cards.sep(),
            cards.text(f"-# الأسعار الخاصة بالأعمال تظهر من زر «تخصيصات الأعمال» • {cards.BOT_SIGNATURE}"),
        ]
        await interaction.message.edit(view=cards.Card(cards.ACCENT_GOLD, *children))

    # ── التخصصات المعطلة ──
    async def _open_disabled(self, interaction: discord.Interaction):
        await interaction.response.defer()
        specialties = SETTINGS.get("specialties", {})
        disabled = [s for s, v in specialties.items() if not v.get("active", True)]
        if disabled:
            lines = [f"• **{s.replace('_', ' ').title()}**" for s in sorted(disabled)]
            body = "هذه التخصصات معطلة ولا تظهر في التسجيل:\n" + "\n".join(lines)
        else:
            body = "لا توجد تخصصات معطلة — كل التخصصات مفعّلة."
        children: list = [
            cards.header(["## التخصصات المعطلة", f"**{len(disabled)}** تخصص معطل حاليًا."],
                         _bot_avatar()),
            cards.sep(2),
            cards.text(body),
            cards.sep(),
            cards.text("-# لإعادة تفعيل تخصص: اختره من قائمة «إدارة تخصص» ثم اضغط تفعيل. ولتفعيل الكل استخدم /تفعيل_تخصص."),
            cards.sep(),
            cards.row(cards.secondary_btn("عودة إلى مركز التخصصات", self._back_cb, emoji="↩")),
            cards.sep(),
            cards.text(f"-# {cards.BOT_SIGNATURE}"),
        ]
        await interaction.message.edit(view=cards.Card(cards.ACCENT_GOLD, *children))

    # ── تخصيصات الأعمال ──
    async def _open_custom(self, interaction: discord.Interaction):
        await interaction.response.defer()
        works = await load_works()
        custom_works = [(w["name"], w.get("custom_prices", {})) for w in works if w.get("custom_prices")]
        children: list = [
            cards.header(["## تخصيصات الأعمال", f"**{len(custom_works)}** عمل له أسعار خاصة."],
                         _bot_avatar()),
            cards.sep(2),
        ]
        if custom_works:
            options = [
                discord.SelectOption(label=cards.clamp(name, 100), value=name,
                                     description=cards.clamp(f"{len(cp)} تخصص بسعر خاص", 100),
                                     emoji="📖")
                for name, cp in custom_works[:25]
            ]
            children.append(cards.text("-# اختر عملاً لعرض أسعاره الخاصة."))
            children.append(cards.sep())
            children.append(cards.make_select("اختر عملاً...", options, self._custom_picked))
        else:
            children.append(cards.text("لا يوجد أي عمل بأسعار خاصة — الجميع على الأسعار العامة.\n"
                                       "لإضافة تخصيص: /تخصيص_سعر_عمل"))
        children += [
            cards.sep(),
            cards.row(cards.secondary_btn("عودة إلى مركز التخصصات", self._back_cb, emoji="↩")),
            cards.sep(),
            cards.text(f"-# {cards.BOT_SIGNATURE}"),
        ]
        await interaction.message.edit(view=cards.Card(cards.ACCENT_GOLD, *children))

    async def _custom_picked(self, interaction: discord.Interaction):
        work_name = interaction.data['values'][0]
        works = await load_works()
        target = next((w for w in works if w["name"] == work_name), None)
        currency = SETTINGS.get('currency', '$') or '$'
        custom = target.get("custom_prices", {}) if target else {}
        lines = [f"• **{spec.replace('_', ' ').title()}** — {currency}{float(price):.2f}"
                 for spec, price in sorted(custom.items(), key=lambda kv: -kv[1])] or ["• لا توجد تخصيصات"]
        children: list = [
            cards.header([f"## تخصيصات {cards.clamp(work_name, 50)}",
                          f"**{len(custom)}** تخصص بسعر خاص — يسري على هذا العمل فقط."],
                         _bot_avatar()),
            cards.sep(2),
            cards.text("\n".join(lines)),
            cards.sep(),
            cards.row(cards.secondary_btn("عودة إلى التخصيصات", self._open_custom_from_detail, emoji="↩")),
            cards.sep(),
            cards.text(f"-# لإزالة كل التخصيصات: /الغاء_تخصيص_عمل • {cards.BOT_SIGNATURE}"),
        ]
        await interaction.response.edit_message(view=cards.Card(cards.ACCENT_GOLD, *children))

    async def _open_custom_from_detail(self, interaction: discord.Interaction):
        await self._open_custom(interaction)

    # ── بطاقة تخصص مفرد ──
    async def _spec_picked(self, interaction: discord.Interaction):
        spec = interaction.data['values'][0]
        view = await SpecialtyDetailView.create(spec, back=self)
        await interaction.response.edit_message(view=view)


class SpecialtyDetailView(ui.LayoutView):
    """بطاقة تخصص واحد: السعر، الحالة، الاستخدام الكلي وفي الشهر الحالي،
    وزر تفعيل/تعطيل ينفّذ فورًا + رجوع إلى المركز."""

    def __init__(self, spec: str, back=None, custom_works: list | None = None):
        super().__init__(timeout=600.0)
        self.spec = spec
        self.back = back
        self.custom_works = custom_works or []
        self.usage_all = 0
        self.usage_month = 0

    @classmethod
    async def create(cls, spec: str, back=None):
        try:
            all_counts, month_counts = await specialty_usage_counts()
        except DatabaseUnavailableError:
            all_counts, month_counts = {}, {}
        # أين يُستخدم هذا التخصص بسعر خاص؟
        custom_lines = []
        try:
            currency = SETTINGS.get('currency', '$') or '$'
            works = await load_works()
            for w in works:
                cp = w.get("custom_prices", {})
                if spec in cp:
                    custom_lines.append(f"• عمل **{w['name']}** — {currency}{float(cp[spec]):.2f}")
        except Exception:
            pass
        self = cls(spec, back, custom_lines)
        self.usage_all = all_counts.get(spec, 0)
        self.usage_month = month_counts.get(spec, 0)
        return self.rebuild()

    def rebuild(self):
        self.clear_items()
        currency = SETTINGS.get('currency', '$') or '$'
        specialties = SETTINGS.get("specialties", {})
        v = specialties.get(self.spec, {})
        is_active = v.get("active", True)
        price = v.get("price", 0.0)
        status_line = "نشط ويظهر في أوامر التسجيل" if is_active else "معطل ولا يظهر في أوامر التسجيل"
        children: list = [
            cards.header([f"## تخصص {self.spec.replace('_', ' ').title()}",
                          status_line], _bot_avatar()),
            cards.sep(2),
            cards.text(
                f"**السعر العام:** {currency}{price:.2f} لكل فصل\n"
                f"**الحالة:** {'نشط' if is_active else 'معطل'}\n"
                f"**السجلات الكلية:** {self.usage_all} سجل (كل الشهور)\n"
                f"**سجلات الشهر الحالي:** {self.usage_month} سجل"
            ),
        ]
        if self.custom_works:
            children.append(cards.sep())
            children.append(cards.text("### أسعار خاصة\n" + "\n".join(self.custom_works)))
        children += [
            cards.sep(),
            cards.row(
                cards.secondary_btn("تفعيل" if not is_active else "تعطيل", self._toggle),
                cards.secondary_btn("عودة إلى المركز", self._back_cb, emoji="↩"),
            ),
            cards.sep(),
            cards.text("-# لتعديل السعر: /تعديل_سعر — ولنقله لعمل محدد: /نقل_تخصص_للخاص"),
            cards.sep(),
            cards.text(f"-# {cards.BOT_SIGNATURE}"),
        ]
        self.add_item(cards.container(cards.ACCENT_GOLD if is_active else cards.ACCENT_GRAY, *children))
        return self

    async def _back_cb(self, interaction: discord.Interaction):
        parent = await _resolve(self.back)
        if parent is None:
            await interaction.response.defer()
            return
        await interaction.response.edit_message(view=parent)

    async def _toggle(self, interaction: discord.Interaction):
        specialties = SETTINGS.get("specialties", {})
        if self.spec not in specialties:
            await interaction.response.send_message(view=cards.error_card(
                "التخصص غير موجود", ["ربما حُذف للتو."], avatar_url=_bot_avatar()), ephemeral=True)
            return
        new_state = not specialties[self.spec].get("active", True)
        specialties[self.spec]["active"] = new_state
        specialties[self.spec]["last_modified"] = datetime.utcnow().isoformat()
        saved = await save_settings(SETTINGS)
        if not saved:
            await interaction.response.send_message(view=cards.error_card(
                "تعذر الحفظ", ["قاعدة البيانات غير متاحة — لم يُطبق التغيير."],
                avatar_url=_bot_avatar()), ephemeral=True)
            return
        rebuild_prices()
        await log_audit("تبديل_حالة_تخصص", interaction.user.id, None,
                        f"{self.spec} ← {'مفعل' if new_state else 'معطل'}")
        self.rebuild()
        await interaction.response.edit_message(view=self)


# ═══════════════════════════════════════════════════════════════
# الأمر
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="تخصصات", description="مركز التخصصات: الأسعار والحالة والاستخدام والتخصيصات (للإدارة)")
@app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id, i.command.qualified_name))
async def specialties_hub(interaction: discord.Interaction):
    if not is_admin(interaction):
        await log_unauthorized(interaction.user.id, "تخصصات")
        await interaction.response.send_message(view=cards.permission_card(_bot_avatar()), ephemeral=True)
        return
    view = await SpecialtiesHubView.create()
    await interaction.response.send_message(view=view)
