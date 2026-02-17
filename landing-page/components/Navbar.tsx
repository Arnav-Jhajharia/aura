"use client";

import { motion } from "framer-motion";

interface NavbarProps {
  visible: boolean;
}

export default function Navbar({ visible }: NavbarProps) {
  if (!visible) return null;

  return (
    <motion.nav
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className="fixed top-5 left-1/2 -translate-x-1/2 z-50 flex items-center gap-4 px-5 py-2.5 rounded-full"
      style={{
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        background: "rgba(255,255,255,0.05)",
        border: "1px solid rgba(255,255,255,0.08)",
      }}
    >
      <span
        className="text-lg tracking-[0.02em]"
        style={{ fontFamily: "var(--font-serif)", color: "var(--color-warm)" }}
      >
        donna
      </span>

      <a
        href="https://wa.me/6583383940"
        target="_blank"
        rel="noopener noreferrer"
        className="text-sm px-4 py-1.5 rounded-full text-white font-medium hover:brightness-110 transition-all"
        style={{
          background: "var(--color-green)",
          fontFamily: "var(--font-sans)",
        }}
      >
        Add on WhatsApp
      </a>
    </motion.nav>
  );
}
