"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";

export default function Navbar() {
  const [visible, setVisible] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => {
      setVisible(window.scrollY > window.innerHeight * 0.5);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Close menu on anchor click
  function handleLink() {
    setMenuOpen(false);
  }

  return (
    <AnimatePresence>
      {visible && (
        <motion.nav
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -12 }}
          transition={{ duration: 0.4, ease: "easeOut" }}
          className="fixed top-4 left-1/2 -translate-x-1/2 z-[100] w-[calc(100%-32px)] max-w-fit"
        >
          {/* Main pill */}
          <div
            className="flex items-center gap-8 px-5 py-2.5 rounded-full border border-white/[0.06]"
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

            {/* Desktop links */}
            <div className="hidden md:flex items-center gap-6">
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

            {/* Mobile hamburger */}
            <button
              onClick={() => setMenuOpen(!menuOpen)}
              className="md:hidden flex flex-col gap-[5px] p-1 cursor-pointer"
              aria-label="Toggle menu"
            >
              <span
                className="block w-[18px] h-[1.5px] bg-[var(--color-text-primary)] transition-transform origin-center"
                style={{
                  transform: menuOpen
                    ? "rotate(45deg) translate(2px, 2px)"
                    : "none",
                }}
              />
              <span
                className="block w-[18px] h-[1.5px] bg-[var(--color-text-primary)] transition-opacity"
                style={{ opacity: menuOpen ? 0 : 1 }}
              />
              <span
                className="block w-[18px] h-[1.5px] bg-[var(--color-text-primary)] transition-transform origin-center"
                style={{
                  transform: menuOpen
                    ? "rotate(-45deg) translate(2px, -2px)"
                    : "none",
                }}
              />
            </button>
          </div>

          {/* Mobile dropdown */}
          <AnimatePresence>
            {menuOpen && (
              <motion.div
                initial={{ opacity: 0, y: -8, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -8, scale: 0.95 }}
                transition={{ duration: 0.2, ease: "easeOut" }}
                className="md:hidden mt-2 rounded-2xl border border-white/[0.06] p-5 flex flex-col gap-4"
                style={{
                  background: "rgba(12, 14, 20, 0.85)",
                  backdropFilter: "blur(20px)",
                  WebkitBackdropFilter: "blur(20px)",
                }}
              >
                <a
                  href="#how-it-works"
                  onClick={handleLink}
                  className="text-[15px] text-white/50 hover:text-white transition-colors"
                >
                  How it works
                </a>
                <a
                  href="#features"
                  onClick={handleLink}
                  className="text-[15px] text-white/50 hover:text-white transition-colors"
                >
                  Features
                </a>
                <a
                  href="#pricing"
                  onClick={handleLink}
                  className="text-[15px] text-white/50 hover:text-white transition-colors"
                >
                  Pricing
                </a>
                <a
                  href="#"
                  onClick={handleLink}
                  className="text-[14px] font-medium text-[var(--color-bg-dark)] bg-[var(--color-warm)] px-5 py-2.5 rounded-full text-center hover:opacity-90 transition-opacity"
                >
                  Try Donna
                </a>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.nav>
      )}
    </AnimatePresence>
  );
}
