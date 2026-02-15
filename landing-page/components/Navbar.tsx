"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";

export default function Navbar() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const onScroll = () => {
      setVisible(window.scrollY > window.innerHeight * 0.5);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <AnimatePresence>
      {visible && (
        <motion.nav
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -12 }}
          transition={{ duration: 0.4, ease: "easeOut" }}
          className="fixed top-4 left-1/2 -translate-x-1/2 z-[100] flex items-center gap-8 px-5 py-2.5 rounded-full border border-white/[0.06]"
          style={{
            background: "rgba(12, 14, 20, 0.65)",
            backdropFilter: "blur(20px)",
            WebkitBackdropFilter: "blur(20px)",
          }}
        >
          <a
            href="#"
            className="text-[18px] text-[var(--color-warm)]"
            style={{ fontFamily: "var(--font-serif)" }}
          >
            donna
          </a>
          <div className="flex items-center gap-6">
            <a href="#how-it-works" className="text-[13px] text-white/40 hover:text-white transition-colors whitespace-nowrap">
              How it works
            </a>
            <a href="#features" className="text-[13px] text-white/40 hover:text-white transition-colors whitespace-nowrap">
              Features
            </a>
            <a href="#pricing" className="text-[13px] text-white/40 hover:text-white transition-colors whitespace-nowrap">
              Pricing
            </a>
            <a
              href="#"
              className="text-[13px] font-medium text-[var(--color-bg-dark)] bg-[var(--color-warm)] px-4 py-1.5 rounded-full hover:opacity-90 transition-opacity whitespace-nowrap"
            >
              Try Donna
            </a>
          </div>
        </motion.nav>
      )}
    </AnimatePresence>
  );
}
