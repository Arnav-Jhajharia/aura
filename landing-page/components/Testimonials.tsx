"use client";

import { useRef } from "react";
import { motion, useInView } from "framer-motion";

const TESTIMONIALS = [
  {
    quote:
      "I used to lose ideas between meetings. Now I just text Donna and she brings them back exactly when I need them. It feels like cheating.",
    name: "Priya Sharma",
    role: "Product Manager, Grab",
    initials: "PS",
  },
  {
    quote:
      "My ADHD brain generates 200 thoughts an hour. Donna is the only thing that's ever kept up. I literally don't know how I survived before this.",
    name: "Marcus Chen",
    role: "Founder, Stealth Startup",
    initials: "MC",
  },
  {
    quote:
      "I asked Donna what my wife mentioned wanting for her birthday three months ago. She remembered. I looked like a hero. 10/10.",
    name: "James Okafor",
    role: "Software Engineer",
    initials: "JO",
  },
];

export default function Testimonials() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-15%" });

  return (
    <section ref={ref} className="relative w-full py-32 px-6">
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
          Testimonials
        </p>
        <h2
          className="font-normal leading-[1.1] tracking-[-0.02em] text-[var(--color-text-primary)]"
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: "clamp(34px, 4.5vw, 54px)",
          }}
        >
          People who
          <br />
          <em className="italic text-[var(--color-warm)]">
            stopped forgetting.
          </em>
        </h2>
      </motion.div>

      <div className="max-w-[1000px] mx-auto grid grid-cols-1 md:grid-cols-3 gap-5">
        {TESTIMONIALS.map((t, i) => (
          <motion.div
            key={t.name}
            initial={{ opacity: 0, y: 30 }}
            animate={inView ? { opacity: 1, y: 0 } : {}}
            transition={{
              duration: 0.6,
              ease: "easeOut",
              delay: 0.12 * (i + 1),
            }}
            className="relative rounded-2xl border border-white/[0.05] p-6 flex flex-col"
            style={{ background: "rgba(255,255,255,0.015)" }}
          >
            {/* Quote mark */}
            <span
              className="block text-[48px] leading-none mb-2"
              style={{
                fontFamily: "var(--font-serif)",
                color: "rgba(196,149,106,0.15)",
              }}
            >
              &ldquo;
            </span>

            <p className="text-[14px] leading-[1.7] text-[var(--color-text-primary)]/70 font-light flex-1 mb-6">
              {t.quote}
            </p>

            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-full bg-[var(--color-warm)]/10 flex items-center justify-center">
                <span className="text-[11px] font-medium text-[var(--color-warm)]">
                  {t.initials}
                </span>
              </div>
              <div>
                <p className="text-[13px] font-medium text-[var(--color-text-primary)] leading-tight">
                  {t.name}
                </p>
                <p className="text-[11px] text-[var(--color-text-muted)] leading-tight">
                  {t.role}
                </p>
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </section>
  );
}
