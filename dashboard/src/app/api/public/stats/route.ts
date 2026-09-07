import { getStore } from "@/lib/store";
import { buildOverview } from "@/lib/agg";
import { json } from "@/lib/api";

/** إحصائيات عامة لصفحة الهبوط — أرقام مجمّعة فقط بلا أي بيانات أعضاء */
export async function GET() {
  try {
    const store = getStore();
    const ov = await buildOverview(store, store.mode);
    return json({
      mode: ov.mode,
      members: ov.totals.members,
      works: ov.totals.works,
      chapters: ov.totals.chapters,
      revenue: ov.totals.revenue,
      activeMonthName: ov.activeMonthName,
      lastUpdated: ov.lastUpdated,
    });
  } catch (e) {
    console.error("[PUBLIC/STATS]", e);
    return json({ mode: "demo", members: 0, works: 0, chapters: 0, revenue: 0, activeMonthName: "", lastUpdated: new Date().toISOString() });
  }
}
