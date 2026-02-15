"use client";

import { createContext, useContext, useState, useCallback } from "react";
import OnboardingModal from "./OnboardingModal";

const OnboardingContext = createContext<() => void>(() => {});

export function useOnboarding() {
  return useContext(OnboardingContext);
}

export default function OnboardingProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const openModal = useCallback(() => setOpen(true), []);

  return (
    <OnboardingContext value={openModal}>
      {children}
      <OnboardingModal open={open} onClose={() => setOpen(false)} />
    </OnboardingContext>
  );
}
