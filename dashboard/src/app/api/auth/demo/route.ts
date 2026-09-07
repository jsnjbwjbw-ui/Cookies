import { setSessionCookie } from "@/lib/session";
import { json } from "@/lib/api";

/** دخول تجريبي — يعمل فقط عندما لا يكون OAuth مربوطًا (بيئة المعاينة) */
export async function POST() {
  const { oauthEnabled } = { oauthEnabled: Boolean(process.env.DISCORD_CLIENT_ID && process.env.DISCORD_CLIENT_SECRET) };
  if (oauthEnabled) {
    return json({ error: "الوضع التجريبي معطّل — OAuth مفعّل. سجّل الدخول عبر ديسكورد." }, 403);
  }
  await setSessionCookie({
    id: "1095961975277756426",
    username: "owner-demo",
    globalName: "أبورين (تجريبي)",
    isAdmin: true,
    demo: true,
  });
  return json({ ok: true });
}
