import { getStore } from "@/lib/store";
import { json, requireAuth, isResponse } from "@/lib/api";
import { logAudit } from "@/lib/audit";
import { DISCORD_API } from "@/lib/discord";

/**
 * مزامنة الأعضاء من ديسكورد — تحتاج DISCORD_BOT_TOKEN + DISCORD_GUILD_ID.
 * تجلب كل أعضاء السيرفر وتحدّث مجموعة members بالاسم والنك والأفاتار،
 * فيظهر النك نيم الحقيقي في الداشبورد فورًا.
 */
export async function POST() {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  if (!auth.isAdmin) return json({ error: "للمشرفين فقط" }, 403);

  const token = process.env.DISCORD_BOT_TOKEN;
  const guildId = process.env.DISCORD_GUILD_ID;
  if (!token || !guildId) {
    return json(
      {
        error: "المزامنة تحتاج متغيرين: DISCORD_BOT_TOKEN (توكن البوت نفسه) و DISCORD_GUILD_ID (معرف السيرفر)",
      },
      501
    );
  }

  try {
    const res = await fetch(`${DISCORD_API}/guilds/${guildId}/members?limit=1000`, {
      headers: { Authorization: `Bot ${token}` },
    });
    if (!res.ok) {
      return json({ error: `فشل جلب الأعضاء من ديسكورد (${res.status}) — تأكد أن البوت في السيرفر وله Servers Members Intent` }, 502);
    }
    const members = (await res.json()) as Array<{
      user?: { id: string; username: string; global_name?: string | null; avatar?: string | null };
      nick?: string | null;
    }>;
    const store = getStore();
    let synced = 0;
    for (const m of members) {
      if (!m.user || m.user.bot) continue;
      const avatar = m.user.avatar
        ? `https://cdn.discordapp.com/avatars/${m.user.id}/${m.user.avatar}.${m.user.avatar.startsWith("a_") ? "gif" : "png"}?size=128`
        : undefined;
      await store.upsertMember(m.user.id, {
        username: m.user.username,
        nickname: m.nick || m.user.global_name || undefined,
        avatar,
      });
      synced += 1;
    }
    await logAudit(store, "مزامنة_أعضاء", auth.id, null, `تمت مزامنة ${synced} عضو من ديسكورد`);
    return json({ ok: true, synced });
  } catch (e) {
    console.error("[SYNC]", e);
    return json({ error: "تعذر الاتصال بديسكورد" }, 502);
  }
}
