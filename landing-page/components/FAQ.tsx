"use client";

import { useRef, useState } from "react";
import { motion, useInView, AnimatePresence } from "framer-motion";

const FAQS = [
  {
    q: "How does Donna actually work?",
    a: "You text Donna on WhatsApp — just like texting a friend. She uses AI to understand what you're telling her, stores it in a personal knowledge graph, and surfaces the right information when you ask for it. No app to download, no interface to learn.",
  },
  {
    q: "Is my data private?",
    a: "Absolutely. Your messages are encrypted in transit and at rest. We never sell your data, never use it to train AI models, and we've built our architecture so that even our team can't read your messages. Your thoughts are yours.",
  },
  {
    q: "Do I need to pay for WhatsApp Business or anything extra?",
    a: "Nope. Donna works with your regular WhatsApp account. Just save her number, send a message, and you're in. No extra apps, no special setup.",
  },
  {
    q: "What if I forget to tell Donna something important?",
    a: "That's the beauty of it — you can connect your calendar, email, and other tools so Donna stays in the loop even when you forget. She reads the context so you don't have to remember every detail.",
  },
  {
    q: "Can I use Donna for work stuff?",
    a: "Definitely. Many users use Donna for meeting follow-ups, project tracking, deadline reminders, and brainstorming. The Team plan adds shared knowledge and collaboration features for workgroups.",
  },
  {
    q: "What happens if I cancel?",
    a: "You can export all your data anytime. If you cancel your Pro subscription, you'll drop to the Free plan — your data stays safe, you just have lower message limits. We'll never hold your memories hostage.",
  },
];

function FAQItem({ item, isOpen, onToggle }: {
  item: (typeof FAQS)[number];
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="border-b border-white/[0.05]">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between py-5 text-left cursor-pointer group"
      >
        <span className="text-[15px] font-medium text-[var(--color-text-primary)] pr-4 group-hover:text-[var(--color-warm)] transition-colors">
          {item.q}
        </span>
        <span
          className="shrink-0 w-6 h-6 flex items-center justify-center text-[var(--color-warm)]/50 transition-transform"
          style={{ transform: isOpen ? "rotate(45deg)" : "rotate(0deg)" }}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M7 1v12M1 7h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </span>
      </button>
      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <p className="text-[14px] leading-[1.7] text-[var(--color-text-muted)] font-light pb-5 max-w-[600px]">
              {item.a}
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function FAQ() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-15%" });
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  return (
    <section ref={ref} id="faq" className="relative w-full py-32 px-6">
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-[200px] h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent, rgba(196,149,106,0.2), transparent)",
        }}
      />

      <div className="max-w-[640px] mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.7, ease: "easeOut" }}
          className="text-center mb-14"
        >
          <p className="text-[10px] uppercase tracking-[4px] text-[var(--color-warm)] font-medium mb-5">
            FAQ
          </p>
          <h2
            className="font-normal leading-[1.1] tracking-[-0.02em] text-[var(--color-text-primary)]"
            style={{
              fontFamily: "var(--font-serif)",
              fontSize: "clamp(34px, 4.5vw, 54px)",
            }}
          >
            Questions?
            <br />
            <em className="italic text-[var(--color-warm)]">
              Donna has answers.
            </em>
          </h2>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, ease: "easeOut", delay: 0.15 }}
        >
          {FAQS.map((item, i) => (
            <FAQItem
              key={i}
              item={item}
              isOpen={openIndex === i}
              onToggle={() => setOpenIndex(openIndex === i ? null : i)}
            />
          ))}
        </motion.div>
      </div>
    </section>
  );
}
