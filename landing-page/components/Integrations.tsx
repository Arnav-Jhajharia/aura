"use client";

import { useRef } from "react";
import { motion, useInView } from "framer-motion";
import Lottie from "lottie-react";
import animationData from "@/public/lottie-integrations.json";

export default function Integrations() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-20%" });

  return (
    <section
      ref={ref}
      id="integrations"
      className="relative w-full min-h-screen flex flex-col md:flex-row items-center justify-center px-6 md:px-15 py-20 md:py-25 gap-10 md:gap-15"
      style={{ background: "var(--color-bg-dark)" }}
    >
      {/* Text left */}
      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.8, ease: "easeOut" }}
        className="max-w-[440px] shrink-0 text-center md:text-left"
      >
        <h2
          className="font-normal leading-[1.1] tracking-[-0.02em] text-[var(--color-text-primary)] mb-5"
          style={{ fontFamily: "var(--font-serif)", fontSize: "clamp(36px, 5vw, 58px)" }}
        >
          It all starts with<br />
          <em className="italic text-[var(--color-warm)]">integrations.</em>
        </h2>
        <p className="text-[16px] leading-[1.7] text-[var(--color-text-muted)] font-light max-w-[400px] mx-auto md:mx-0">
          Donna plugs into the tools you already use — your calendar, your courses, your inbox. She reads them so you don&apos;t have to.
        </p>
      </motion.div>

      {/* Lottie right — appears 1s after text */}
      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.8, ease: "easeOut", delay: 1 }}
        className="flex-1 max-w-[580px] min-w-[280px]"
      >
        <Lottie animationData={animationData} loop autoplay />
      </motion.div>
    </section>
  );
}
