import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { setSessionCookie } from "@/lib/session";
import { DISCORD_API, redirectUri, PERM_ADMINISTRATOR, PERM_MANAGE_GUILD } from "@/lib/discord";

interface DiscordUser {
  id: string;
  username: string;
  global_name?: string | null;
  avatar?: string | null;
}

export async function GET(req: Request) {
  const clientId = process.env.DISCORD_CLIENT_ID;
  const clientSecret = process.env.DISCORD_CLIENT_SECRET;
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");

  if (!clientId || !clientSecret || !code) {
    return NextResponse.redirect(new URL("/?auth=error", req.url));
  }

  const store = await cookies();
  const savedState = store.get("ct_oauth_state")?.value;
  if (!state || !savedState || state !== savedState) {
    return NextResponse.redirect(new URL("/?auth=state", req.url));
  }
  store.set("ct_oauth_state", "", { path: "/", maxAge: 0 });

  try {
    const tokenRes = await fetch(`${DISCORD_API}/oauth2/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id: clientId,
        client_secret: clientSecret,
        grant_type: "authorization_code",
        code,
        redirect_uri: redirectUri(req),
      }),
    });
    if (!tokenRes.ok) throw new Error(`token ${tokenRes.status}`);
    const token = (await tokenRes.json()) as { access_token: string };

    const headers = { Authorization: `Bearer ${token.access_token}` };
    const [userRes, guildsRes] = await Promise.all([
      fetch(`${DISCORD_API}/users/@me`, { headers }),
      fetch(`${DISCORD_API}/users/@me/guilds`, { headers }),
    ]);
    if (!userRes.ok) throw new Error(`user ${userRes.status}`);
    const dUser = (await userRes.json()) as DiscordUser;

    let isAdmin = false;
    const ownerIds = (process.env.DISCORD_OWNER_IDS || "").split(",").map((s) => s.trim()).filter(Boolean);
    if (ownerIds.includes(dUser.id)) isAdmin = true;

    if (guildsRes.ok) {
      const guilds = (await guildsRes.json()) as Array<{ id: string; owner: boolean; permissions: string }>;
      const guildId = process.env.DISCORD_GUILD_ID;
      if (guildId) {
        const g = guilds.find((x) => x.id === guildId);
        if (!g) {
          return NextResponse.redirect(new URL("/?auth=notmember", req.url));
        }
        if (g.owner || ownerIds.includes(dUser.id)) isAdmin = true;
        if (!isAdmin) {
          const perms = BigInt(g.permissions || "0");
          if ((perms & PERM_ADMINISTRATOR) !== 0n || (perms & PERM_MANAGE_GUILD) !== 0n) isAdmin = true;
        }
      } else {
        if (guilds.some((g) => g.owner)) isAdmin = true;
      }
    }

    await setSessionCookie({
      id: dUser.id,
      username: dUser.username,
      globalName: dUser.global_name || undefined,
      avatar: dUser.avatar
        ? `https://cdn.discordapp.com/avatars/${dUser.id}/${dUser.avatar}.${dUser.avatar.startsWith("a_") ? "gif" : "png"}?size=128`
        : undefined,
      isAdmin,
    });

    return NextResponse.redirect(new URL("/", req.url));
  } catch (e) {
    console.error("[OAUTH] callback failed:", e);
    return NextResponse.redirect(new URL("/?auth=error", req.url));
  }
}
