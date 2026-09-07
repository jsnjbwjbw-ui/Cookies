import { getStore } from "@/lib/store";
import { isMonthKey, currentMonthKey } from "@/lib/store/types";
import { getActiveMonth } from "@/lib/agg";
import { json, requireAuth, isResponse } from "@/lib/api";
import { logAudit } from "@/lib/audit";

export async function GET() {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  try {
    const store = getStore();
    const [settings, { key, name }] = await Promise.all([store.getSettings(), getActiveMonth(store)]);
    return json({
      settings: {
        currency: settings.currency || "$",
        alert_threshold: settings.alert_threshold ?? 10,
        allowed_channels: settings.allowed_channels || [],
        payment_day: settings.payment_day ?? null,
        active_month: key,
      },
      activeMonthName: name,
    });
  } catch (e) {
    console.error("[SETTINGS/GET]", e);
    return json({ error: "تعذر قراءة الإعدادات" }, 503);
  }
}

export async function PATCH(req: Request) {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  if (!auth.isAdmin) return json({ error: "للمشرفين فقط" }, 403);
  try {
    const body = (await req.json()) as {
      currency?: string;
      alert_threshold?: number;
      active_month?: string;
    };
    const store = getStore();
    const settings = await store.getSettings();
    if (typeof body.currency === "string" && body.currency.trim()) {
      settings.currency = body.currency.trim().slice(0, 4);
    }
    if (typeof body.alert_threshold === "number" && body.alert_threshold >= 0) {
      settings.alert_threshold = body.alert_threshold;
    }
    if (typeof body.active_month === "string" && isMonthKey(body.active_month)) {
      settings.active_month = body.active_month;
    } else if (body.active_month === null) {
      settings.active_month = currentMonthKey();
    }
    const saved = await store.saveSettings(settings);
    if (!saved) return json({ error: "تعذر الحفظ" }, 503);
    await logAudit(store, "تعديل_إعدادات", auth.id, null, JSON.stringify(body).slice(0, 200));
    return json({ ok: true });
  } catch (e) {
    console.error("[SETTINGS/PATCH]", e);
    return json({ error: "تعذر التعديل" }, 500);
  }
}
