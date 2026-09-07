import { clearSessionCookie } from "@/lib/session";
import { json } from "@/lib/api";

export async function POST() {
  await clearSessionCookie();
  return json({ ok: true });
}
