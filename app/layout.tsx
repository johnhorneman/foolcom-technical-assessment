import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Image from "next/image";
import Link from "next/link";
import React, { Suspense } from "react";

import { MockSourcesToolbar } from "@/components/MockSourcesToolbar";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "The Motley Fool",
  description: "Fool.com technical assessment",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <header className="border-b border-zinc-200 dark:border-zinc-800">
          <div className="mx-auto flex w-full max-w-2xl items-center gap-3 px-6 py-4">
            <Link href="/" prefetch={false} className="flex items-center gap-3">
              <Image
                src="/jester-cap.svg"
                alt="The Motley Fool"
                width={63}
                height={30}
                priority
              />
              <span className="text-xl font-bold tracking-tight">
                The Motley Fool
              </span>
            </Link>
          </div>
        </header>
        {children}
        <Suspense>
          <MockSourcesToolbar />
        </Suspense>
      </body>
    </html>
  );
}
