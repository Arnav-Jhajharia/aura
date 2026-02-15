"use client";

import { useRef } from "react";
import { motion, useInView } from "framer-motion";

const FEATURES = [
  {
    title: "WhatsApp native",
    description:
      "No new app. No login. Just text Donna on WhatsApp — the app you already open 80 times a day.",
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
      </svg>
    ),
    span: "col-span-1",
  },
  {
    title: "Context-aware recall",
    description:
      "She doesn't just remember words — she understands meaning. Ask about \"that restaurant Sarah mentioned\" and she'll know.",
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <path d="M12 6v6l4 2" />
      </svg>
    ),
    span: "col-span-1 md:col-span-2",
  },
  {
    title: "Smart reminders",
    description:
      "Donna nudges you at the right moment — not because you set a timer, but because she understood the context.",
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.73 21a2 2 0 0 1-3.46 0" />
      </svg>
    ),
    span: "col-span-1 md:col-span-2",
  },
  {
    title: "Private & encrypted",
    description:
      "Your thoughts are yours. End-to-end encrypted, never sold, never used to train models. We can't read them even if we wanted to.",
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
      </svg>
    ),
    span: "col-span-1",
  },
  {
    title: "Natural language",
    description:
      "No commands. No syntax. Talk to Donna like you'd talk to a friend who never forgets.",
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 20h9" />
        <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
      </svg>
    ),
    span: "col-span-1",
  },
  {
    title: "Always learning",
    description:
      "The more you share, the sharper she gets. Donna builds a personal knowledge graph that grows with your life.",
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
      </svg>
    ),
    span: "col-span-1",
  },
];

export default function Features() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-15%" });

  return (
    <section ref={ref} id="features" className="relative w-full py-32 px-6">
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-[200px] h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent, rgba(196,149,106,0.2), transparent)",
        }}
      />

      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.7, ease: "easeOut" }}
        className="text-center mb-16"
      >
        <p className="text-[10px] uppercase tracking-[4px] text-[var(--color-warm)] font-medium mb-5">
          Features
        </p>
        <h2
          className="font-normal leading-[1.1] tracking-[-0.02em] text-[var(--color-text-primary)]"
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: "clamp(34px, 4.5vw, 54px)",
          }}
        >
          Built for the way
          <br />
          <em className="italic text-[var(--color-warm)]">you actually think.</em>
        </h2>
      </motion.div>

      <div className="max-w-[880px] mx-auto grid grid-cols-1 md:grid-cols-3 gap-4">
        {FEATURES.map((feat, i) => (
          <motion.div
            key={feat.title}
            initial={{ opacity: 0, y: 30 }}
            animate={inView ? { opacity: 1, y: 0 } : {}}
            transition={{
              duration: 0.6,
              ease: "easeOut",
              delay: 0.08 * (i + 1),
            }}
            className={`${feat.span} group relative rounded-2xl border border-white/[0.05] p-6 transition-colors hover:border-[var(--color-warm)]/15`}
            style={{ background: "rgba(255,255,255,0.015)" }}
          >
            <div className="w-10 h-10 rounded-xl bg-[var(--color-warm)]/10 flex items-center justify-center text-[var(--color-warm)] mb-4">
              {feat.icon}
            </div>
            <h3 className="text-[16px] font-medium text-[var(--color-text-primary)] mb-2">
              {feat.title}
            </h3>
            <p className="text-[13.5px] leading-[1.65] text-[var(--color-text-muted)] font-light">
              {feat.description}
            </p>
          </motion.div>
        ))}
      </div>
    </section>
  );
}
