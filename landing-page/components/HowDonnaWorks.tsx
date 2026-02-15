"use client";

import { useRef } from "react";
import { motion, useInView } from "framer-motion";
import Lottie from "lottie-react";
import animationData from "@/public/lottie-integrations.json";

const STEPS = [
  {
    number: "01",
    title: "Dump your brain",
    description:
      "Text Donna like you'd text a friend. Voice notes, half-thoughts, 2am brain dumps — she takes it all.",
    chat: [
      {
        from: "user",
        text: "remind me to get noor earrings for her birthday, also chimichanga opened near campus and arnav wants to meet sunday",
      },
      {
        from: "donna",
        text: "got it — noor's birthday, chimichanga, arnav sunday. i'll handle it.",
      },
    ],
  },
  {
    number: "02",
    title: "She connects the dots",
    description:
      "Donna doesn't just store — she links your thoughts to your calendar, your contacts, and your past conversations.",
    chat: [
      { from: "user", text: "what's this week?" },
      {
        from: "donna",
        text: "SE assignment friday 11:59pm (you're ~60% done). arnav sunday 2pm. noor's birthday is saturday — you said earrings.",
      },
    ],
  },
  {
    number: "03",
    title: "She acts on it",
    description:
      "Donna doesn't wait for you to ask again. She books, reminds, and surfaces things at the right moment — on her own.",
    chat: [
      {
        from: "donna",
        text: "chimichanga has 4.6★ and you're free tonight. want me to text the group?",
      },
      {
        from: "donna",
        text: "noor's birthday is tomorrow. here are 3 earring options under $50.",
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

export default function HowDonnaWorks() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-15%" });
  const ref2 = useRef(null);
  const inView2 = useInView(ref2, { once: true, margin: "-15%" });

  return (
    <section id="how-donna-works" className="relative w-full">
      {/* Subtle top divider */}
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-[200px] h-px"
        style={{
          background: "linear-gradient(90deg, transparent, rgba(196,149,106,0.2), transparent)",
        }}
      />

      {/* Part 1: Integrations */}
      <div
        ref={ref}
        className="w-full min-h-screen flex flex-col md:flex-row items-center justify-center px-6 md:px-15 py-20 md:py-25 gap-10 md:gap-15"
      >
        {/* Text left */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.8, ease: "easeOut" }}
          className="max-w-[440px] shrink-0 text-center md:text-left"
        >
          <p className="text-[10px] uppercase tracking-[4px] text-[var(--color-warm)] font-medium mb-5">
            integrations
          </p>
          <h2
            className="font-normal leading-[1.1] tracking-[-0.02em] text-[var(--color-text-primary)] mb-5"
            style={{ fontFamily: "var(--font-serif)", fontSize: "clamp(36px, 5vw, 58px)" }}
          >
            She already knows<br />
            <em className="italic text-[var(--color-warm)]">your week.</em>
          </h2>
          <p className="text-[16px] leading-[1.7] text-[var(--color-text-muted)] font-light max-w-[400px] mx-auto md:mx-0">
            Donna reads your Google Calendar, Canvas, Gmail, and more — before you even think to check them. Connect once, never update her again.
          </p>
        </motion.div>

        {/* Lottie right */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.8, ease: "easeOut", delay: 1 }}
          className="flex-1 max-w-[580px] min-w-[280px]"
        >
          <Lottie animationData={animationData} loop autoplay />
        </motion.div>
      </div>

      {/* Part 2: The Conversation Loop */}
      <div ref={ref2} className="w-full py-20 md:py-32 px-6">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={inView2 ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.7, ease: "easeOut" }}
          className="text-center mb-14 md:mb-20"
        >
          <p className="text-[10px] uppercase tracking-[4px] text-[var(--color-warm)] font-medium mb-5">
            how it works
          </p>
          <h2
            className="font-normal leading-[1.1] tracking-[-0.02em] text-[var(--color-text-primary)]"
            style={{ fontFamily: "var(--font-serif)", fontSize: "clamp(34px, 4.5vw, 54px)" }}
          >
            You text. She handles<br />
            <em className="italic text-[var(--color-warm)]">the rest.</em>
          </h2>
        </motion.div>

        <div className="max-w-[1040px] mx-auto flex flex-col gap-16 md:gap-24">
          {STEPS.map((step, i) => (
            <motion.div
              key={step.number}
              initial={{ opacity: 0, y: 40 }}
              animate={inView2 ? { opacity: 1, y: 0 } : {}}
              transition={{
                duration: 0.7,
                ease: "easeOut",
                delay: 0.15 * (i + 1),
              }}
              className={`flex items-center gap-10 md:gap-16 ${
                i % 2 === 1 ? "md:flex-row-reverse" : ""
              } flex-col md:flex-row`}
            >
              {/* Text side */}
              <div className="flex-1 min-w-0 text-center md:text-left">
                <span
                  className="block text-[36px] md:text-[48px] font-light leading-none mb-4"
                  style={{
                    fontFamily: "var(--font-serif)",
                    color: "rgba(196,149,106,0.15)",
                  }}
                >
                  {step.number}
                </span>
                <h3
                  className="text-[24px] md:text-[28px] font-normal leading-[1.2] tracking-[-0.01em] text-[var(--color-text-primary)] mb-3"
                  style={{ fontFamily: "var(--font-serif)" }}
                >
                  {step.title}
                </h3>
                <p className="text-[15px] leading-[1.7] text-[var(--color-text-muted)] font-light max-w-[380px] mx-auto md:mx-0">
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
      </div>
    </section>
  );
}
