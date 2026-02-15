"use client";

import { useRef } from "react";
import { motion, useInView } from "framer-motion";

export default function FinalCTA() {
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

      {/* Warm radial glow behind */}
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[400px] pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse, rgba(196,149,106,0.06) 0%, transparent 70%)",
        }}
      />

      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.8, ease: "easeOut" }}
        className="relative text-center max-w-[560px] mx-auto"
      >
        <h2
          className="font-normal leading-[1.1] tracking-[-0.02em] text-[var(--color-text-primary)] mb-5"
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: "clamp(36px, 5vw, 60px)",
          }}
        >
          Your next thought
          <br />
          <em className="italic text-[var(--color-warm)]">
            deserves to be remembered.
          </em>
        </h2>

        <p className="text-[16px] leading-[1.7] text-[var(--color-text-muted)] font-light max-w-[400px] mx-auto mb-10">
          Stop trusting your brain with things that matter. Let Donna carry the
          weight — so you can carry on.
        </p>

        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <button className="bg-[var(--color-warm)] text-[var(--color-bg-dark)] px-9 py-3.5 rounded-full text-[14px] font-medium tracking-[0.01em] hover:-translate-y-0.5 hover:shadow-[0_6px_30px_rgba(196,149,106,0.25)] transition-all cursor-pointer">
            Try Donna free
          </button>
          <span className="text-[12px] text-[var(--color-text-muted)] font-light">
            No app download. Just WhatsApp.
          </span>
        </div>
      </motion.div>
    </section>
  );
}
