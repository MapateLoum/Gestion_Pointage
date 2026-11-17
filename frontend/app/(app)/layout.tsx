import type { ReactNode } from "react";
import { SessionProvider } from "@/components/session";
import { Shell } from "@/components/shell";
import { ToastProvider } from "@/components/toast";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <ToastProvider>
      <SessionProvider>
        <Shell>{children}</Shell>
      </SessionProvider>
    </ToastProvider>
  );
}
