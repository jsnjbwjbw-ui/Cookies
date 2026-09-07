import type { Metadata, Viewport } from "next";
import { Cairo } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/sonner";

const cairo = Cairo({
  variable: "--font-cairo",
  subsets: ["arabic", "latin"],
  weight: ["400", "500", "600", "700", "800", "900"],
});

export const metadata: Metadata = {
  title: "Cookies Tracker — لوحة تحكم فريق كوكيز",
  description:
    "الداشبورد الرسمي لبوت Cookies Tracker: إدارة الأعضاء والأعمال والسجلات والأشهر والتخصصات، مترابط مع البوت وتحديث لحظي.",
  icons: { icon: "/cookie-logo.png" },
  openGraph: {
    title: "Cookies Tracker",
    description: "لوحة تحكم فريق كوكيز — قوة البوت بوجهٍ أقوى.",
    type: "website",
  },
};

export const viewport: Viewport = {
  themeColor: "#050505",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ar" dir="rtl" suppressHydrationWarning>
      <body className={`${cairo.variable} font-sans antialiased bg-background text-foreground min-h-screen`}>
        {children}
        <Toaster position="top-center" richColors theme="dark" closeButton />
      </body>
    </html>
  );
}
