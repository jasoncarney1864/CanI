import type { Metadata } from "next";
import { DM_Sans, Source_Serif_4 } from "next/font/google";
import "./globals.css";

// Dual-stack typography (§4):
//   UI & System Control -> DM Sans
//   Content Payload     -> Source Serif Pro (published on Google Fonts as "Source Serif 4")
const dmSans = DM_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-ui",
  display: "swap",
});

const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  weight: ["400", "600"],
  variable: "--font-content",
  display: "swap",
});

export const metadata: Metadata = {
  title: "CanI \u2014 Illuminated Clarity",
  description:
    "Design-language prototype for CanI: the Spotlight layout and Spoke token framework.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${dmSans.variable} ${sourceSerif.variable}`}>
      <body>{children}</body>
    </html>
  );
}
