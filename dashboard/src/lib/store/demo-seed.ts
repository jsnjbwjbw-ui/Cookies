import type { RecordEntry, WorkDoc, MemberDoc, MonthDoc, AuditDoc, SettingsDoc } from "./types";
import { DEFAULT_SPECIALTIES, BONUS_WORK_NAME } from "./defaults";

/** بيانات تجريبية غنية وواقعية لفريق كوكيز — تُستخدم فقط عندما لا يوجد MONGODB_URI */

export const DEMO_MEMBERS: Array<{ id: string; username: string; nickname: string }> = [
  { id: "1095961975277756426", username: "aboreen", nickname: "أبورين" },
  { id: "5123409876543210001", username: "kirby", nickname: "كيربي" },
  { id: "5123409876543210002", username: "zeno", nickname: "زينو" },
  { id: "5123409876543210003", username: "meedo", nickname: "ميدو" },
  { id: "5123409876543210004", username: "rayan", nickname: "ريّان" },
  { id: "5123409876543210005", username: "nova", nickname: "نوفا" },
  { id: "5123409876543210006", username: "sama", nickname: "ساما" },
  { id: "5123409876543210007", username: "toshi", nickname: "توشي" },
  { id: "5123409876543210008", username: "lova", nickname: "لوفا" },
  { id: "5123409876543210009", username: "qio", nickname: "كيو" },
];

export const DEMO_WORKS: WorkDoc[] = [
  { name: "سولو ليفلنج", paid_start: 12 },
  { name: "ناروتو: الجيل الجديد" },
  { name: "سياف النهاية", custom_prices: { تحرير: 0.75, تبييض: 0.3 } },
  { name: "وحش البدايات" },
  { name: "أكاديميا القمة", paid_start: 1 },
  { name: "قاعدة الليل" },
  { name: "بطل الدرع", isolated: true },
];

function mulberry(seed: number) {
  return function () {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const SPECIALTIES = Object.keys(DEFAULT_SPECIALTIES);

function priceFor(work: WorkDoc, type: string): number {
  if (work.custom_prices && type in work.custom_prices) return work.custom_prices[type];
  return DEFAULT_SPECIALTIES[type]?.price ?? 0.05;
}

export function buildDemoData(now = new Date()): {
  records: Record<string, RecordEntry[]>;
  works: WorkDoc[];
  members: Record<string, MemberDoc>;
  months: MonthDoc[];
  settings: SettingsDoc;
  audit: AuditDoc[];
} {
  const rnd = mulberry(20250607);
  const records: Record<string, RecordEntry[]> = {};
  const members: Record<string, MemberDoc> = {};
  const months: MonthDoc[] = [];
  const audit: AuditDoc[] = [];

  const cur = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
  const prev = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1));
  const curKey = cur.toISOString().slice(0, 7);
  const prevKey = prev.toISOString().slice(0, 7);

  months.push({
    _id: prevKey,
    name: "شهر العاصفة",
    created_at: prev.toISOString(),
    created_by: DEMO_MEMBERS[0].id,
  });
  months.push({
    _id: curKey,
    name: "شهر كوكيز",
    created_at: cur.toISOString(),
    created_by: DEMO_MEMBERS[0].id,
  });

  for (const m of DEMO_MEMBERS) {
    members[m.id] = {
      _id: m.id,
      username: m.username,
      nickname: m.nickname,
      first_seen: prev.toISOString(),
      last_seen: now.toISOString(),
    };
  }

  const activeWorks = DEMO_WORKS.filter((w) => !w.isolated);

  function entriesForMonth(monthStart: Date, key: string, volume: number) {
    const daysInMonth = new Date(Date.UTC(monthStart.getUTCFullYear(), monthStart.getUTCMonth() + 1, 0)).getUTCDate();
    const lastDay = key === curKey ? Math.min(now.getUTCDate(), daysInMonth) : daysInMonth;

    DEMO_MEMBERS.forEach((m, mi) => {
      // أبورين مالك أقل نشاطًا؛ بعض الأعضاء أبطال الشهر
      const hero = mi === 0 ? 0.4 : 0.7 + ((mi * 7) % 9) / 14;
      const count = Math.max(0, Math.round(volume * hero * (0.6 + rnd() * 0.8)));
      for (let i = 0; i < count; i++) {
        const work = activeWorks[Math.floor(rnd() * activeWorks.length)];
        const type = SPECIALTIES[Math.floor(rnd() * SPECIALTIES.length)];
        const day = 1 + Math.floor(rnd() * lastDay);
        const ts = new Date(Date.UTC(monthStart.getUTCFullYear(), monthStart.getUTCMonth(), day, 10 + Math.floor(rnd() * 12), Math.floor(rnd() * 60)));
        if (ts > now) continue;
        const chapter = String(1 + Math.floor(rnd() * 180));
        const entry: RecordEntry = {
          work_name: work.name,
          chapter,
          work_type: type,
          total: priceFor(work, type),
          notes: rnd() < 0.12 ? "جودة عالية — يُراجع قبل الرفع" : "",
          timestamp: ts.toISOString(),
          month_key: key,
          username: m.username,
        };
        (records[m.id] ||= []).push(entry);
      }
    });

    // مكافآت وخصومات واقعية
    const bonus = DEMO_MEMBERS[1 + Math.floor(rnd() * (DEMO_MEMBERS.length - 1))];
    (records[bonus.id] ||= []).push({
      work_name: BONUS_WORK_NAME,
      chapter: "مكافأة",
      work_type: "مكافأة",
      total: 2,
      notes: "إنجاز شهر كامل قبل الموعد",
      timestamp: new Date(Math.min(monthStart.getTime() + 18 * 86400000, now.getTime())).toISOString(),
      month_key: key,
      username: bonus.username,
      added_by: DEMO_MEMBERS[0].id,
    });
    const ded = DEMO_MEMBERS[2 + Math.floor(rnd() * (DEMO_MEMBERS.length - 2))];
    (records[ded.id] ||= []).push({
      work_name: BONUS_WORK_NAME,
      chapter: "خصم",
      work_type: "خصم",
      total: -0.5,
      notes: "تأخير تسليم دفعة فصول",
      timestamp: new Date(Math.min(monthStart.getTime() + 22 * 86400000, now.getTime())).toISOString(),
      month_key: key,
      username: ded.username,
      added_by: DEMO_MEMBERS[0].id,
    });
  }

  entriesForMonth(prev, prevKey, 14);
  entriesForMonth(cur, curKey, 11);

  for (const uid of Object.keys(records)) {
    records[uid].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  }

  const auditSamples: Array<[string, string, string]> = [
    ["تسجيل_عمل", "كيربي سجل 4 فصول في سولو ليفلنج", "4"],
    ["مكافأة", "مكافأة 2.00 - السبب: إنجاز شهر كامل قبل الموعد", "2"],
    ["إضافة_عمل", "أُضيف العمل سياف النهاية", "0"],
    ["تحديد_قنوات", "تم تحديد قناة التسجيل", "0"],
    ["خصم", "خصم 0.50 - السبب: تأخير تسليم دفعة فصول", "1"],
    ["تبديل_شهر", "تم تفعيل الشهر الحالي", "0"],
  ];
  auditSamples.forEach(([action, details, targetIdx], i) => {
    const target = Number(targetIdx) > 0 ? DEMO_MEMBERS[Number(targetIdx)]?.id : null;
    audit.push({
      action,
      moderator_id: DEMO_MEMBERS[0].id,
      target_id: target,
      details,
      timestamp: new Date(now.getTime() - (i + 1) * 3600_000 * (2 + i)).toISOString(),
    });
  });

  const settings: SettingsDoc = {
    allowed_channels: ["تسجيـــــــــل-اعمال〢💵", "ム・💎〢شات・اونر"],
    currency: "$",
    notify_channel_id: null,
    daily_backup_channel_id: null,
    alert_threshold: 10.0,
    specialties: {
      ...DEFAULT_SPECIALTIES,
      تنسيق: { price: 0.35, active: false, last_modified: prev.toISOString() },
    },
    payment_day: 1,
    payment_hour: 0,
    active_month: curKey,
  };

  return { records, works: DEMO_WORKS, members, months, settings, audit };
}
