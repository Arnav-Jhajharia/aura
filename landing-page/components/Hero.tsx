"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { motion } from "framer-motion";
import { useVisitorData } from "@/hooks/useVisitorData";

interface HeroProps {
  onComplete: () => void;
}

export default function Hero({ onComplete }: HeroProps) {
  const visitorData = useVisitorData();

  // --- instant reveal for returning visitors / reduced motion ---
  const [instantReveal, setInstantReveal] = useState(false);

  // --- sequence state ---
  const [visibleCount, setVisibleCount] = useState(0);
  const [dimmed, setDimmed] = useState(false);
  const [turnVisible, setTurnVisible] = useState(false);

  // --- reveal state ---
  const [showReveal, setShowReveal] = useState(false);
  const [wordmarkVisible, setWordmarkVisible] = useState(false);
  const [subtextVisible, setSubtextVisible] = useState(false);
  const [ctaVisible, setCtaVisible] = useState(false);

  const [skipVisible, setSkipVisible] = useState(false);
  const [sequenceComplete, setSequenceComplete] = useState(false);

  const timeoutsRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const sequenceStartedRef = useRef(false);

  // --- check returning visitor + reduced motion on mount ---
  useEffect(() => {
    const isReturning = !!localStorage.getItem("donna_hero_seen");
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;

    if (isReturning || reducedMotion) {
      setInstantReveal(true);
      setShowReveal(true);
      setWordmarkVisible(true);
      setSubtextVisible(true);
      setCtaVisible(true);
      setSequenceComplete(true);
      onComplete();
    }
  }, [onComplete]);

  // --- compute observation lines ---
  const lines = useMemo(() => {
    if (visitorData.isLoading) return [];

    const result: string[] = [];

    if (visitorData.city) {
      result.push(`You're in ${visitorData.city}.`);
    }

    const timeLine = visitorData.timeCommentary
      ? `It's ${visitorData.timeString}. ${visitorData.timeCommentary}`
      : `It's ${visitorData.timeString}.`;
    result.push(timeLine);

    result.push(visitorData.deviceLine);

    result.push("You have something due this week you haven't started.");
    result.push("There's a message you keep meaning to reply to.");
    result.push("You had an idea last week you've already forgotten.");
    result.push("You told yourself this semester would be different.");

    return result;
  }, [visitorData]);

  const phase1Count = useMemo(() => {
    if (visitorData.isLoading) return 0;
    return visitorData.city ? 3 : 2;
  }, [visitorData.city, visitorData.isLoading]);

  const turnLine = "What if someone was actually paying attention?";

  // --- build & run the timeline ---
  const startSequence = useCallback(() => {
    if (instantReveal || lines.length === 0) return;

    const ids: ReturnType<typeof setTimeout>[] = [];
    const schedule = (ms: number, fn: () => void) => {
      ids.push(setTimeout(fn, ms));
    };

    // absolute timeline
    let t = 1000; // initial black-screen hold

    // Phase 1: real-data lines
    for (let i = 0; i < phase1Count; i++) {
      if (i > 0) t += i === 1 ? 1200 : 1000;
      const idx = i + 1;
      schedule(t, () => setVisibleCount(idx));
    }

    // pause before phase 2
    t += 1800;

    // Phase 2: universal truths
    const phase2Delays = [0, 1400, 1400, 1800];
    for (let i = 0; i < 4; i++) {
      t += phase2Delays[i];
      const idx = phase1Count + i + 1;
      schedule(t, () => setVisibleCount(idx));
    }

    // pause before dim + turn
    t += 2500;

    // dim lines 1-7
    schedule(t, () => setDimmed(true));

    // turn line 200ms after dim starts
    t += 200;
    schedule(t, () => setTurnVisible(true));

    // pause: 800ms animation + 2000ms hold
    t += 2800;

    // transition to reveal
    schedule(t, () => setShowReveal(true));

    t += 400;
    schedule(t, () => setWordmarkVisible(true));

    t += 300;
    schedule(t, () => setSubtextVisible(true));

    t += 400;
    schedule(t, () => setCtaVisible(true));

    t += 500;
    schedule(t, () => {
      setSequenceComplete(true);
      localStorage.setItem("donna_hero_seen", "1");
      onComplete();
    });

    // skip button after 3s
    schedule(3000, () => setSkipVisible(true));

    timeoutsRef.current = ids;
  }, [instantReveal, lines, phase1Count, onComplete]);

  // trigger sequence when data is ready
  useEffect(() => {
    if (
      !visitorData.isLoading &&
      !instantReveal &&
      !sequenceStartedRef.current
    ) {
      sequenceStartedRef.current = true;
      startSequence();
    }
    return () => {
      timeoutsRef.current.forEach(clearTimeout);
    };
  }, [visitorData.isLoading, instantReveal, startSequence]);

  // --- skip handler ---
  const handleSkip = useCallback(() => {
    timeoutsRef.current.forEach(clearTimeout);
    timeoutsRef.current = [];
    setSkipVisible(false);
    setDimmed(true);
    setShowReveal(true);

    const ids: ReturnType<typeof setTimeout>[] = [];
    ids.push(setTimeout(() => setWordmarkVisible(true), 100));
    ids.push(setTimeout(() => setSubtextVisible(true), 200));
    ids.push(setTimeout(() => setCtaVisible(true), 300));
    ids.push(
      setTimeout(() => {
        setSequenceComplete(true);
        localStorage.setItem("donna_hero_seen", "1");
        onComplete();
      }, 500)
    );
    timeoutsRef.current = ids;
  }, [onComplete]);

  // --- body scroll lock ---
  useEffect(() => {
    if (!sequenceComplete) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [sequenceComplete]);

  // --- render ---
  return (
    <section
      className="relative min-h-screen"
      style={{
        background: showReveal ? "var(--color-bg-reveal)" : "var(--color-bg)",
        transition: "background 1.5s ease",
      }}
    >
      {/* warm glow behind wordmark */}
      {showReveal && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div
            className="glow-pulse"
            style={{
              width: "600px",
              height: "400px",
              background:
                "radial-gradient(ellipse at center, rgba(196,149,106,0.06) 0%, transparent 70%)",
              borderRadius: "50%",
            }}
          />
        </div>
      )}

      {/* ---- sequence layer (observation lines) ---- */}
      <div
        className="absolute inset-0 flex items-center justify-center"
        style={{
          opacity: showReveal ? 0 : 1,
          transition: "opacity 800ms ease-in-out",
          pointerEvents: showReveal ? "none" : "auto",
        }}
      >
        <div className="text-center px-6 flex flex-col items-center gap-4 md:gap-5">
          {lines.slice(0, visibleCount).map((line, i) => (
            <motion.p
              key={`line-${i}`}
              initial={{ opacity: 0, y: 12 }}
              animate={{
                opacity: dimmed ? 0.25 : 1,
                y: 0,
              }}
              transition={{
                opacity: { duration: dimmed ? 0.8 : 0.6, ease: "easeOut" },
                y: { duration: 0.6, ease: "easeOut" },
              }}
              className="text-[17px] md:text-[22px] leading-relaxed font-light"
              style={{
                fontFamily: "var(--font-sans)",
                color: "var(--color-text)",
              }}
            >
              {line}
            </motion.p>
          ))}

          {turnVisible && (
            <motion.p
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.8, ease: "easeOut" }}
              className="text-[22px] md:text-[30px] leading-relaxed italic mt-2"
              style={{
                fontFamily: "var(--font-serif)",
                color: "var(--color-warm)",
              }}
            >
              {turnLine}
            </motion.p>
          )}
        </div>
      </div>

      {/* ---- reveal layer (wordmark + CTA) ---- */}
      <div
        className="absolute inset-0 flex items-center justify-center"
        style={{
          opacity: showReveal ? 1 : 0,
          transition: "opacity 800ms ease-in-out",
          pointerEvents: showReveal ? "auto" : "none",
        }}
      >
        <div className="text-center px-6 flex flex-col items-center">
          {/* turn line echoed at top of reveal */}
          <p
            className="text-[22px] md:text-[30px] leading-relaxed italic mb-8 md:mb-12"
            style={{
              fontFamily: "var(--font-serif)",
              color: "var(--color-warm)",
              opacity: showReveal ? 1 : 0,
            }}
          >
            {turnLine}
          </p>

          {/* wordmark */}
          <motion.h1
            initial={instantReveal ? false : { opacity: 0, y: 12 }}
            animate={
              wordmarkVisible ? { opacity: 1, y: 0 } : { opacity: 0, y: 12 }
            }
            transition={{ duration: 0.8, ease: "easeOut" }}
            className="text-[40px] md:text-[56px] leading-none tracking-[0.02em] mb-4 md:mb-6"
            style={{
              fontFamily: "var(--font-serif)",
              color: "var(--color-warm)",
            }}
          >
            donna
          </motion.h1>

          {/* subtext */}
          <motion.div
            initial={instantReveal ? false : { opacity: 0, y: 12 }}
            animate={
              subtextVisible ? { opacity: 1, y: 0 } : { opacity: 0, y: 12 }
            }
            transition={{ duration: 0.6, ease: "easeOut" }}
            className="mb-8 md:mb-10"
          >
            <p
              className="text-[15px] md:text-lg font-light"
              style={{ color: "var(--color-text-muted)" }}
            >
              Your AI assistant on WhatsApp.
            </p>
            <p
              className="text-[15px] md:text-lg font-light"
              style={{ color: "var(--color-text-muted)" }}
            >
              She remembers everything you forget.
            </p>
          </motion.div>

          {/* CTA */}
          <motion.a
            href="https://wa.me/6583383940"
            target="_blank"
            rel="noopener noreferrer"
            initial={instantReveal ? false : { opacity: 0, y: 12 }}
            animate={
              ctaVisible ? { opacity: 1, y: 0 } : { opacity: 0, y: 12 }
            }
            transition={{ duration: 0.6, ease: "easeOut" }}
            className="inline-block px-8 py-3.5 rounded-full text-white text-[15px] font-medium
                       hover:brightness-110 hover:scale-[1.02] transition-all duration-200
                       w-full sm:w-auto max-w-xs sm:max-w-none text-center"
            style={{
              background: "var(--color-green)",
              fontFamily: "var(--font-sans)",
            }}
          >
            Add Donna on WhatsApp
          </motion.a>
        </div>
      </div>

      {/* ---- skip button ---- */}
      {skipVisible && !showReveal && (
        <motion.button
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3 }}
          onClick={handleSkip}
          className="absolute bottom-4 right-4 md:bottom-6 md:right-6 text-xs cursor-pointer
                     hover:opacity-80 transition-opacity focus:outline-none focus:ring-1
                     focus:ring-white/20 rounded px-2 py-1"
          style={{
            fontFamily: "var(--font-sans)",
            color: "var(--color-text-dim)",
          }}
        >
          Skip →
        </motion.button>
      )}
    </section>
  );
}
