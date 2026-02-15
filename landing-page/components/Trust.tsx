"use client";

import { useRef } from "react";
import { motion, useInView } from "framer-motion";

const TRUST_CARDS = [
  {
    title: "End-to-end encrypted",
    description:
      "Every message, every memory, every connection — encrypted in transit and at rest. We literally cannot read your data.",
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
      </svg>
    ),
    highlight: false,
  },
  {
    title: "Never used for training",
    description:
      "Your thoughts are yours. We never use your data to train AI models. Not now, not ever. It's in our terms.",
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
        <circle cx="12" cy="12" r="3" />
        <line x1="1" y1="1" x2="23" y2="23" />
      </svg>
    ),
    highlight: false,
  },
  {
    title: "Delete everything, anytime",
    description:
      'One message to Donna: "forget everything." And she does. Complete data deletion, no questions, no 30-day wait.',
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="3 6 5 6 21 6" />
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      </svg>
    ),
    highlight: false,
  },
  {
    title: "Open source brain",
    description:
      "Donna's intelligence layer is open source. See exactly how she thinks, what she stores, and what she sends. No black boxes.",
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="16 18 22 12 16 6" />
        <polyline points="8 6 2 12 8 18" />
      </svg>
    ),
    highlight: true,
    link: "https://github.com/Arnav-Jhajharia/aura",
  },
];

export default function Trust() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-15%" });

  return (
    <section ref={ref} id="trust" className="relative w-full py-20 md:py-32 px-6">
      {/* Subtle top divider line */}
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-[200px] h-px"
        style={{
          background: "linear-gradient(90deg, transparent, rgba(196,149,106,0.2), transparent)",
        }}
      />

      {/* Section header */}
      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.7, ease: "easeOut" }}
        className="text-center mb-16"
      >
        <p className="text-[10px] uppercase tracking-[4px] text-[var(--color-warm)] font-medium mb-5">
          your privacy
        </p>
        <h2
          className="font-normal leading-[1.1] tracking-[-0.02em] text-[var(--color-text-primary)]"
          style={{ fontFamily: "var(--font-serif)", fontSize: "clamp(34px, 4.5vw, 54px)" }}
        >
          Your brain.{" "}
          <em className="italic text-[var(--color-warm)]">Not ours.</em>
        </h2>
        <p className="text-[16px] leading-[1.7] text-[var(--color-text-muted)] font-light max-w-[480px] mx-auto mt-5">
          Donna is built to know everything about you — and tell no one. Here&apos;s how we keep it that way.
        </p>
      </motion.div>

      {/* Trust cards — 1x4 desktop, 2x2 tablet, 1x1 mobile */}
      <div className="max-w-[1080px] mx-auto grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {TRUST_CARDS.map((card, i) => (
          <motion.div
            key={card.title}
            initial={{ opacity: 0, y: 30 }}
            animate={inView ? { opacity: 1, y: 0 } : {}}
            transition={{
              duration: 0.6,
              ease: "easeOut",
              delay: 0.08 * (i + 1),
            }}
            className={`relative rounded-2xl border p-6 transition-colors hover:border-[var(--color-warm)]/15 ${
              card.highlight
                ? "border-[var(--color-warm)]/15"
                : "border-white/[0.05]"
            }`}
            style={{ background: "rgba(255,255,255,0.015)" }}
          >
            <div className="w-10 h-10 rounded-xl bg-[var(--color-warm)]/10 flex items-center justify-center text-[var(--color-warm)] mb-4">
              {card.icon}
            </div>
            <h3 className="text-[16px] font-medium text-[var(--color-text-primary)] mb-2">
              {card.title}
            </h3>
            <p className="text-[13.5px] leading-[1.65] text-[var(--color-text-muted)] font-light">
              {card.description}
            </p>
            {card.link && (
              <a
                href={card.link}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block mt-3 text-[12px] text-[var(--color-warm)]/70 hover:text-[var(--color-warm)] transition-colors font-medium"
              >
                View on GitHub &rarr;
              </a>
            )}
          </motion.div>
        ))}
      </div>

      {/* Credibility bar */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={inView ? { opacity: 1 } : {}}
        transition={{ duration: 0.6, ease: "easeOut", delay: 0.5 }}
        className="mt-16 text-center"
      >
        <p className="text-[11px] uppercase tracking-[3px] text-[var(--color-text-dim)] font-light">
          Built by NUS engineering students &middot; Powered by GPT-4 &middot; WhatsApp Business API &middot; Open source on GitHub
        </p>
      </motion.div>
    </section>
  );
}
