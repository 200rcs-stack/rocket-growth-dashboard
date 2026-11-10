import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Rocket Desk · 왓니몰",
  description: "근거를 확인하고, 다음 행동을 결정하는 로켓그로스 운영 데스크",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body className="antialiased">{children}</body>
    </html>
  );
}
