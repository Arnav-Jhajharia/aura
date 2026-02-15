"use client";

import { useRef } from "react";
import { motion, useInView } from "framer-motion";

const STEPS = [
  {
    number: "01",
    title: "Tell Donna anything",
    description:
      "Text her on WhatsApp like you would a friend. Random thought at 2am? A brilliant idea in the shower? Just send it.",
    chat: [
      { from: "user", text: "remind me to call the landlord about the leak" },
      { from: "donna", text: "Got it. I'll remind you tomorrow at 10am." },
    ],
  },
  {
    number: "02",
    title: "She connects the dots",
    description:
      "Donna doesn't just store — she understands. She links your thoughts, deadlines, and ideas into a web of context only she can see.",
    chat: [
      { from: "user", text: "what did I say about the trip to Bali?" },
      {
        from: "donna",
        text: "On Jan 12 you said you wanted to go in March, budget around $2k. You also mentioned inviting Sarah.",
      },
    ],
  },
  {
    number: "03",
    title: "Ask anytime",
    description:
      "Need something? Just ask. Donna surfaces exactly what you need — no scrolling, no searching, no digging through apps.",
    chat: [
      { from: "user", text: "what's on my plate this week?" },
      {
        from: "donna",
        text: "You have a dentist appt Tuesday, Sara's birthday Thursday, and the report is due Friday.",
      },
    ],
  },
];

function ChatBubble({ from, text }: { from: string; text: string }) {
  const isUser = from === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] px-3.5 py-2.5 text-[12.5px] leading-[1.55] ${
          isUser
            ? "bg-[#005C4B] text-[#E9EDEF] rounded-[10px_10px_3px_10px]"
            : "bg-[#1A1D23] text-[var(--color-text-primary)] rounded-[10px_10px_10px_3px] border border-white/[0.04]"
        }`}
      >
        {!isUser && (
          <span className="block text-[10px] font-medium text-[var(--color-warm)] mb-0.5">
            Donna
          </span>
        )}
        {text}
      </div>
    </div>
  );
}

export default function HowItWorks() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-15%" });

  return (
    <section
      ref={ref}
      id="how-it-works"
      className="relative w-full py-32 px-6"
    >
      {/* Subtle top divider */}
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
        className="text-center mb-20"
      >
        <p className="text-[10px] uppercase tracking-[4px] text-[var(--color-warm)] font-medium mb-5">
          How it works
        </p>
        <h2
          className="font-normal leading-[1.1] tracking-[-0.02em] text-[var(--color-text-primary)]"
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: "clamp(34px, 4.5vw, 54px)",
          }}
        >
          Three messages.
          <br />
          <em className="italic text-[var(--color-warm)]">That&apos;s it.</em>
        </h2>
      </motion.div>

      <div className="max-w-[1040px] mx-auto flex flex-col gap-24">
        {STEPS.map((step, i) => (
          <motion.div
            key={step.number}
            initial={{ opacity: 0, y: 40 }}
            animate={inView ? { opacity: 1, y: 0 } : {}}
            transition={{
              duration: 0.7,
              ease: "easeOut",
              delay: 0.15 * (i + 1),
            }}
            className={`flex items-center gap-16 ${
              i % 2 === 1 ? "flex-row-reverse" : ""
            } max-md:flex-col max-md:gap-8`}
          >
            {/* Text side */}
            <div className="flex-1 min-w-0">
              <span
                className="block text-[48px] font-light leading-none mb-4"
                style={{
                  fontFamily: "var(--font-serif)",
                  color: "rgba(196,149,106,0.15)",
                }}
              >
                {step.number}
              </span>
              <h3
                className="text-[28px] font-normal leading-[1.2] tracking-[-0.01em] text-[var(--color-text-primary)] mb-3"
                style={{ fontFamily: "var(--font-serif)" }}
              >
                {step.title}
              </h3>
              <p className="text-[15px] leading-[1.7] text-[var(--color-text-muted)] font-light max-w-[380px]">
                {step.description}
              </p>
            </div>

            {/* Chat mockup side */}
            <div className="flex-1 min-w-0 max-w-[380px] w-full">
              <div className="relative rounded-2xl overflow-hidden border border-white/[0.05] bg-[#0B0F13]">
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

                {/* Messages */}
                <div className="flex flex-col gap-2.5 p-4">
                  {step.chat.map((msg, mi) => (
                    <ChatBubble key={mi} from={msg.from} text={msg.text} />
                  ))}
                </div>
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </section>
  );
}
