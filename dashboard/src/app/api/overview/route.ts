import { getStore } from "@/lib/store";
import { buildOverview } from "@/lib/agg";
import { json, requireAuth, isResponse } from "@/lib/api";

export async function GET() {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  try {
    const store = getStore();
    const ov = await buildOverview(store, store.mode);
    return json(ov);
  } catch (e) {
    console.error("[OVERVIEW]", e);
    return json({ error: "تعذر قراءة البيانات من قاعدة البيانات" }, 503);
  }
}
