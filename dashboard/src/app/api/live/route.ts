import { getStore } from "@/lib/store";
import { buildLiveEvents } from "@/lib/agg";
import { json, requireAuth, isResponse } from "@/lib/api";

export const dynamic = "force-dynamic";

/** بث الأحداث الحية — مع نبض تجريبي في وضع المعاينة */
export async function GET() {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  try {
    const store = getStore();
    let pulse = null;
    if (store.mode === "demo") {
      try {
        pulse = await (store as unknown as { pulse?: () => Promise<unknown> }).pulse?.() ?? null;
      } catch {
        pulse = null;
      }
    }
    const [events, records, dbUp] = await Promise.all([buildLiveEvents(store), store.getRecords(), store.ping()]);
    const totalRecords = Object.values(records).reduce((s, e) => s + e.length, 0);
    return json({ events, pulse, totalRecords, dbUp, serverTime: new Date().toISOString() });
  } catch (e) {
    console.error("[LIVE]", e);
    return json({ error: "تعذر قراءة البث" }, 503);
  }
}
