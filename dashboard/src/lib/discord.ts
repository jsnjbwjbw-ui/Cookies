export const DISCORD_API = "https://discord.com/api/v10";

export function redirectUri(req: Request): string {
  const url = new URL(req.url);
  const proto = req.headers.get("x-forwarded-proto") || url.protocol.replace(":", "");
  const host = req.headers.get("x-forwarded-host") || req.headers.get("host") || url.host;
  return `${proto}://${host}/api/auth/discord/callback`;
}

export const PERM_ADMINISTRATOR = 1n << 3n;
export const PERM_MANAGE_GUILD = 1n << 5n;
