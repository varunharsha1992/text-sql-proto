"use client";

import { UploadContext, useUploadState } from "@/lib/hooks";
import NavBar from "@/components/NavBar";
import type { ReactNode } from "react";

export default function AppProviders({ children }: { children: ReactNode }) {
  const state = useUploadState();
  return (
    <UploadContext.Provider value={state}>
      <NavBar />
      {children}
    </UploadContext.Provider>
  );
}

