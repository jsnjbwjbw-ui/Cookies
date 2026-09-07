# Cookies Tracker — لوحة التحكم (Dashboard)

لوحة ويب متكاملة لبوت **Cookies Tracker** — بديل أقوى لواجهة البوت بتحكم كامل،
بالهوية الذهبية على الأسود وشعار الكوكيز، تعمل حتى على الأجهزة الضعيفة
(كل المؤثرات CSS خفيفة + `prefers-reduced-motion`).

- تسجيل دخول عبر **Discord OAuth2** (يرتبط بالبوت: فحص عضوية السيرفر وصلاحيات المالك).
- **كل بيانات البوت في الموقع**: الأعضاء، الأعمال، السجلات، الأشهر، التخصصات، الإعدادات.
- **تحديث بالوقت الفعلي** بين البوت والموقع (نفس قاعدة MongoDB + بث مباشر).
- وضعان: **live** (MONGODB_URI → نفس قاعدة البوت، مزامنة باتجاهين) و **demo**
  (بدون متغيرات — بيانات تجريبية غنية + نبض حي، للتجربة قبل الربط).

---

## التشغيل محليًا

```bash
bun install        # أو npm install
cp .env.example .env   # عبّئ القيم ثم:
bun run dev
```

## النشر

### Vercel (الموصى به للمواقع)
1. ارفع المستودع واختر مجلد `dashboard` كـ Root Directory.
2. أضف متغيرات البيئة من `.env.example`.
3. انسخ نطاق الموقع بعد النشر لضبط OAuth (الخطوة التالية).

### Railway / أي استضافة Node
- Root Directory: `dashboard`
- Build: `bun install && bun run build` — Start: `bun run start`
- أو بنفس الأوامر بـ npm: `npm install && npm run build` ثم `npm run start`

## ربط ديسكورد (إجباري لتفعيل الدخول الحقيقي)

1. https://discord.com/developers/applications → تطبيق البوت نفسه → **OAuth2**.
2. أضف Redirect: `https://<نطاق-الداشبورد>/api/auth/discord/callback`
3. عبّئ `DISCORD_CLIENT_ID` و `DISCORD_CLIENT_SECRET` و `DISCORD_GUILD_ID`.
4. أنشئ `SESSION_SECRET` عشوائيًا: `openssl rand -hex 32`.

> بدون متغيرات OAuth يعمل زر **الدخول التجريبي** فقط — مفيد للمعاينة،
> ويُستحسن تركه متاحًا كشاشة عرض عامة.

## الربط مع البوت (مزامنة حية)

الموقع يقرأ ويكتب **نفس مجموعات MongoDB** التي يستخدمها البوت مباشرة
(`records`, `works`, `members`, `months`, `settings`, `audit_log`) بنفس
الأشكال الدقيقة، مع نفس حراسات عدم المسح — أي تسجيل من الموقع يظهر في
البوت فورًا والعكس صحيح.

المتطلبات:
- `MONGODB_URI` = نفس قيمة البوت، ويفضَّل **MongoDB Atlas خارجي**
  (`mongodb+srv://...`) — روابط MongoDB الداخلية من Railway تُحذف مع انتهاء
  الخطة وهي سبب "فقدان" البيانات سابقًا.
- `MONGODB_DB_NAME` = نفس اسم قاعدة البوت.

عند توفر `DISCORD_BOT_TOKEN` تعرض شاشة الإعدادات حالة اتصال البوت الحقيقية.

## بنية المشروع

```
src/
  app/api/          14 مسار API (auth, overview, members, works, records,
                    months, specialties, settings, live, public/stats, sync)
  app/page.tsx      نقطة الدخول: هبوط سينمائي ثم لوحة بعد الدخول
  components/site/  صفحة الهبوط (هيرو، ماركي، عدّادات، مميزات، محاكي المجموعات)
  components/dash/  قوقعة اللوحة + 8 شاشات إدارية + مؤثرات fx
  lib/store/        MongoStore (نفس قاعدة البوت) | DemoStore (تجريبي)
  lib/session.ts    جلسات موقعة HMAC داخل كوكي httpOnly
```

## ملاحظات

- لا يوجد Prisma ولا SQLite — طبقة البيانات هي MongoDB فقط (عبر `mongodb` driver).
- وضع demo يحفظ في `db/demo-store.json` (يُزرع تلقائيًا، خارج git).
- لطرد أخطاء الكود: `bun run lint`.
