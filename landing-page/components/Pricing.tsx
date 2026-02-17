"use client";

import { useRef } from "react";
import { motion, useInView } from "framer-motion";
import { useOnboarding } from "./OnboardingProvider";

const PLANS = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    description: "For students who forget things.",
    features: [
      "50 messages / month",
      "Basic recall",
      "WhatsApp integration",
      "7-day memory",
    ],
    cta: "Start free",
    highlighted: false,
  },
  {
    name: "Pro",
    price: "$8",
    period: "/ month",
    description: "For students who think too much.",
    features: [
      "Unlimited messages",
      "Full memory — she never forgets",
      "Smart proactive reminders",
      "Calendar, Canvas, Outlook & email sync",
      "Voice note transcription",
      "Priority support",
    ],
    cta: "Try Donna Pro",
    highlighted: true,
  },
];

export default function Pricing() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-15%" });
  const openOnboarding = useOnboarding();

  return (
    <section ref={ref} id="pricing" className="relative w-full py-20 md:py-32 px-6">
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
          Pricing
        </p>
        <h2
          className="font-normal leading-[1.1] tracking-[-0.02em] text-[var(--color-text-primary)]"
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: "clamp(34px, 4.5vw, 54px)",
          }}
        >
          Remember everything.
          <br />
          <em className="italic text-[var(--color-warm)]">Pay almost nothing.</em>
        </h2>
      </motion.div>

      <div className="max-w-[800px] mx-auto grid grid-cols-1 md:grid-cols-2 gap-5 items-start">
        {PLANS.map((plan, i) => (
          <motion.div
            key={plan.name}
            initial={{ opacity: 0, y: 36 }}
            animate={inView ? { opacity: 1, y: 0 } : {}}
            transition={{
              duration: 0.6,
              ease: "easeOut",
              delay: 0.12 * (i + 1),
            }}
            className={`relative rounded-2xl border p-7 flex flex-col max-w-[380px] mx-auto w-full ${
              plan.highlighted
                ? "border-[var(--color-warm)]/25 bg-[var(--color-warm)]/[0.03]"
                : "border-white/[0.05] bg-white/[0.015]"
            }`}
          >
            {plan.highlighted && (
              <span className="absolute -top-3 left-1/2 -translate-x-1/2 text-[10px] uppercase tracking-[3px] font-medium text-[var(--color-bg-dark)] bg-[var(--color-warm)] px-3 py-1 rounded-full">
                Popular
              </span>
            )}

            <h3 className="text-[14px] font-medium text-[var(--color-text-muted)] uppercase tracking-[2px] mb-4">
              {plan.name}
            </h3>

            <div className="flex items-baseline gap-1 mb-1">
              <span
                className="text-[42px] font-normal leading-none text-[var(--color-text-primary)]"
                style={{ fontFamily: "var(--font-serif)" }}
              >
                {plan.price}
              </span>
              <span className="text-[13px] text-[var(--color-text-muted)] font-light">
                {plan.period}
              </span>
            </div>
            <p className="text-[13px] text-[var(--color-text-muted)] font-light mb-6">
              {plan.description}
            </p>

            <ul className="flex flex-col gap-2.5 mb-8 flex-1">
              {plan.features.map((feat) => (
                <li
                  key={feat}
                  className="flex items-start gap-2.5 text-[13.5px] leading-[1.5] text-[var(--color-text-primary)]/70 font-light"
                >
                  <svg
                    width="15"
                    height="15"
                    viewBox="0 0 15 15"
                    fill="none"
                    className="mt-0.5 shrink-0 text-[var(--color-warm)]"
                  >
                    <path
                      d="M3.5 7.5L6.5 10.5L11.5 4.5"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  {feat}
                </li>
              ))}
            </ul>

            <button
              onClick={openOnboarding}
              className={`w-full py-3 rounded-full text-[13px] font-medium tracking-[0.01em] transition-all cursor-pointer ${
                plan.highlighted
                  ? "bg-[var(--color-warm)] text-[var(--color-bg-dark)] hover:shadow-[0_6px_30px_rgba(196,149,106,0.2)] hover:-translate-y-0.5"
                  : "bg-white/[0.06] text-[var(--color-text-primary)] hover:bg-white/[0.1]"
              }`}
            >
              {plan.cta}
            </button>
          </motion.div>
        ))}
      </div>
    </section>
  );
}
