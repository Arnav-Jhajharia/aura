"use client";

import { useEffect, useRef, useCallback } from "react";
import Lenis from "lenis";

export default function SmoothScroll({ children }: { children: React.ReactNode }) {
  const lenisRef = useRef<Lenis | null>(null);
  const isSnapping = useRef(false);
  const cooldown = useRef(false);

  const getSections = useCallback((): HTMLElement[] => {
    return Array.from(document.querySelectorAll<HTMLElement>(
      "section, footer"
    ));
  }, []);

  const getCurrentSectionIndex = useCallback((sections: HTMLElement[]) => {
    const scrollY = window.scrollY;
    const vh = window.innerHeight;
    // Find the section whose top is closest to the current scroll position
    let closest = 0;
    let closestDist = Infinity;
    for (let i = 0; i < sections.length; i++) {
      const dist = Math.abs(sections[i].offsetTop - scrollY - vh * 0.15);
      if (dist < closestDist) {
        closestDist = dist;
        closest = i;
      }
    }
    return closest;
  }, []);

  useEffect(() => {
    const lenis = new Lenis({
      duration: 1.4,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      touchMultiplier: 2,
    });
    lenisRef.current = lenis;

    function raf(time: number) {
      lenis.raf(time);
      requestAnimationFrame(raf);
    }
    requestAnimationFrame(raf);

    // --- Scroll snap on wheel ---
    function handleWheel(e: WheelEvent) {
      // Don't interfere if user is inside a scrollable child
      const target = e.target as HTMLElement;
      if (target.closest("[data-lenis-prevent]")) return;

      // Debounce — ignore rapid-fire wheel events
      if (cooldown.current || isSnapping.current) return;

      // Only snap on meaningful scroll (ignore trackpad micro-movements)
      if (Math.abs(e.deltaY) < 30) return;

      const sections = getSections();
      if (sections.length === 0) return;

      const current = getCurrentSectionIndex(sections);
      const direction = e.deltaY > 0 ? 1 : -1;
      const next = Math.max(0, Math.min(sections.length - 1, current + direction));

      if (next === current) return;

      isSnapping.current = true;
      cooldown.current = true;

      lenis.scrollTo(sections[next], {
        offset: 0,
        duration: 1.4,
        onComplete: () => {
          isSnapping.current = false;
        },
      });

      // Cooldown prevents rapid section-skipping
      setTimeout(() => {
        cooldown.current = false;
      }, 900);
    }

    // --- Touch snap ---
    let touchStartY = 0;
    function handleTouchStart(e: TouchEvent) {
      touchStartY = e.touches[0].clientY;
    }

    function handleTouchEnd(e: TouchEvent) {
      if (cooldown.current || isSnapping.current) return;

      const deltaY = touchStartY - e.changedTouches[0].clientY;
      if (Math.abs(deltaY) < 50) return; // Ignore small swipes

      const sections = getSections();
      if (sections.length === 0) return;

      const current = getCurrentSectionIndex(sections);
      const direction = deltaY > 0 ? 1 : -1;
      const next = Math.max(0, Math.min(sections.length - 1, current + direction));

      if (next === current) return;

      isSnapping.current = true;
      cooldown.current = true;

      lenis.scrollTo(sections[next], {
        offset: 0,
        duration: 1.4,
        onComplete: () => {
          isSnapping.current = false;
        },
      });

      setTimeout(() => {
        cooldown.current = false;
      }, 900);
    }

    // --- Anchor clicks ---
    function handleAnchor(e: MouseEvent) {
      const anchor = (e.target as HTMLElement).closest("a[href^='#']");
      if (!anchor) return;
      const href = anchor.getAttribute("href");
      if (!href || href === "#") return;
      const el = document.querySelector(href);
      if (!el) return;
      e.preventDefault();
      lenis.scrollTo(el as HTMLElement, { offset: 0, duration: 1.4 });
    }

    window.addEventListener("wheel", handleWheel, { passive: true });
    window.addEventListener("touchstart", handleTouchStart, { passive: true });
    window.addEventListener("touchend", handleTouchEnd, { passive: true });
    document.addEventListener("click", handleAnchor);

    return () => {
      window.removeEventListener("wheel", handleWheel);
      window.removeEventListener("touchstart", handleTouchStart);
      window.removeEventListener("touchend", handleTouchEnd);
      document.removeEventListener("click", handleAnchor);
      lenis.destroy();
    };
  }, [getSections, getCurrentSectionIndex]);

  return <>{children}</>;
}
