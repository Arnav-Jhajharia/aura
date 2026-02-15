"use client";

import { useRef } from "react";
import { motion, useInView } from "framer-motion";

const MESSAGES = [
  {
    time: "8:12 AM",
    text: "morning. you've got 3 things today: 9am lecture, 2pm arnav, SE due friday. there's a 3-hour gap after lunch — block it for SE?",
    source: "pulled from google calendar",
  },
  {
    time: "12:34 PM",
    text: "prof rao just replied to your email. tl;dr: office hours moved to thursday 3pm.",
    source: "pulled from outlook",
  },
  {
    time: "2:45 PM",
    text: "heads up — new canvas announcement in CS3203. extra credit closes tomorrow.",
    source: "pulled from canvas",
  },
  {
    time: "6:47 PM",
    text: "you mentioned chimichanga 2 weeks ago. it's 4.6★, 8 min walk, and you're free tonight. want me to text the group?",
    source: "remembered from oct 28 + maps",
  },
  {
    time: "10:15 PM",
    text: "you said you'd call mom tonight. it's 10:15.",
    source: "remembered from yesterday",
  },
];

export default function DonnaTextsFirst() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-15%" });

  return (
    <section ref={ref} id="donna-texts-first" className="relative w-full py-20 md:py-32 px-6">
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
          what makes donna different
        </p>
        <h2
          className="font-normal leading-[1.1] tracking-[-0.02em] text-[var(--color-text-primary)]"
          style={{ fontFamily: "var(--font-serif)", fontSize: "clamp(34px, 4.5vw, 54px)" }}
        >
          She texts you{" "}
          <em className="italic text-[var(--color-warm)]">first.</em>
        </h2>
        <p className="text-[16px] leading-[1.7] text-[var(--color-text-muted)] font-light max-w-[480px] mx-auto mt-5">
          Most assistants wait for you to ask. Donna watches your calendar, your deadlines, your life — and speaks up when something matters.
        </p>
      </motion.div>

      {/* Phone mockup */}
      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.6, ease: "easeOut", delay: 0.15 }}
        className="flex justify-center"
      >
        {/* Subtle glow behind phone */}
        <div className="relative">
          <div
            className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[600px] pointer-events-none"
            style={{
              background: "radial-gradient(ellipse, rgba(196,149,106,0.04) 0%, transparent 70%)",
            }}
          />

          {/* Floating phone animation wrapper */}
          <motion.div
            animate={{ y: [0, -4, 0] }}
            transition={{ duration: 6, ease: "easeInOut", repeat: Infinity }}
          >
            {/* Phone frame */}
            <div
              className="relative w-full max-w-[380px] rounded-[40px] border border-white/[0.06] overflow-hidden"
              style={{ background: "#0B0F13" }}
            >
              {/* Notch */}
              <div className="flex justify-center pt-3 pb-1">
                <div className="w-[120px] h-[28px] rounded-full bg-black/60" />
              </div>

              {/* WhatsApp-style header */}
              <div className="flex items-center gap-3 px-4 py-3 bg-[#111418] border-b border-white/[0.04]">
                <div className="w-8 h-8 rounded-full bg-[var(--color-warm)]/20 flex items-center justify-center">
                  <span
                    className="text-[13px] text-[var(--color-warm)]"
                    style={{ fontFamily: "var(--font-serif)" }}
                  >
                    d
                  </span>
                </div>
                <div>
                  <p className="text-[13px] text-[var(--color-text-primary)] font-medium leading-tight">
                    Donna
                  </p>
                  <p className="text-[10px] text-[var(--color-warm)]/60 leading-tight">
                    online
                  </p>
                </div>
              </div>

              {/* Day label */}
              <div className="flex justify-center py-3">
                <span className="text-[10px] uppercase tracking-[2px] text-[var(--color-text-dim)] font-medium">
                  A day with Donna
                </span>
              </div>

              {/* Messages */}
              <div className="flex flex-col gap-4 px-4 pb-6">
                {MESSAGES.map((msg, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 16 }}
                    animate={inView ? { opacity: 1, y: 0 } : {}}
                    transition={{
                      duration: 0.5,
                      ease: "easeOut",
                      delay: 0.3 + i * 0.3,
                    }}
                    className="flex flex-col gap-1"
                  >
                    {/* Timestamp */}
                    <span className="text-[10px] text-[var(--color-text-dim)] text-center mb-1">
                      {msg.time}
                    </span>

                    {/* Donna bubble — left aligned */}
                    <div className="flex justify-start">
                      <div className="max-w-[85%] px-3.5 py-2.5 text-[12.5px] leading-[1.55] bg-[#1A1D23] text-[var(--color-text-primary)] rounded-[10px_10px_10px_3px] border border-white/[0.04]">
                        <span className="block text-[10px] font-medium text-[var(--color-warm)] mb-0.5">
                          Donna
                        </span>
                        {msg.text}
                      </div>
                    </div>

                    {/* Source tag */}
                    <span className="text-[10px] text-[var(--color-text-dim)] font-light ml-1">
                      {msg.source}
                    </span>
                  </motion.div>
                ))}
              </div>

              {/* Bottom home indicator */}
              <div className="flex justify-center pb-3 pt-1">
                <div className="w-[100px] h-[4px] rounded-full bg-white/[0.08]" />
              </div>
            </div>
          </motion.div>
        </div>
      </motion.div>
    </section>
  );
}
