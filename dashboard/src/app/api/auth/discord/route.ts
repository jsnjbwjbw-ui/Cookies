import crypto from "node:crypto";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { redirectUri } from "@/lib/discord";

/** يبدأ تدفق OAuth2 الخاص بديسكورد */
export async function GET(req: Request) {
  const clientId = process.env.DISCORD_CLIENT_ID;
  if (!clientId || !process.env.DISCORD_CLIENT_SECRET) {
    return NextResponse.json({ error: "OAuth غير مفعّل — اضبط DISCORD_CLIENT_ID و DISCORD_CLIENT_SECRET" }, { status: 501 });
  }
  const state = crypto.randomBytes(16).toString("hex");
  const store = await cookies();
  store.set("ct_oauth_state", state, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 600,
  });
  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri(req),
    response_type: "code",
    scope: "identify guilds",
    state,
    prompt: "consent",
  });
  return NextResponse.redirect(`https://discord.com/oauth2/authorize?${params}`);
}
