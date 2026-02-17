"use client";

import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { QRCodeSVG } from "qrcode.react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const WA_NUMBER = process.env.NEXT_PUBLIC_WHATSAPP_NUMBER || "";

function useIsMobile() {
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const check = () => setMobile(/iPhone|iPad|iPod|Android/i.test(navigator.userAgent));
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);
  return mobile;
}

// ── Step types ──────────────────────────────────────────────
type Step = "choice" | "phone" | "google" | "canvas" | "outlook" | "nusmods" | "verify";

const INTEGRATION_STEPS: Step[] = ["google", "canvas", "outlook", "nusmods"];

function nextStep(current: Step): Step {
  const idx = INTEGRATION_STEPS.indexOf(current);
  if (idx === -1 || idx >= INTEGRATION_STEPS.length - 1) return "verify";
  return INTEGRATION_STEPS[idx + 1];
}

function generateCode() {
  return String(Math.floor(1000 + Math.random() * 9000));
}

// ── Shared UI ───────────────────────────────────────────────
function Overlay({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
      className="fixed inset-0 z-[200] flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 20, scale: 0.97 }}
        transition={{ duration: 0.25, ease: "easeOut" }}
        className="relative w-full max-w-[420px] max-h-[90vh] overflow-y-auto rounded-2xl border border-white/[0.06] p-8"
        style={{ background: "rgba(14, 17, 23, 0.97)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute top-4 right-4 w-7 h-7 flex items-center justify-center text-white/25 hover:text-white/60 transition-colors cursor-pointer"
          aria-label="Close"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
        {children}
      </motion.div>
    </motion.div>
  );
}

function StepDots({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center justify-center gap-1.5 mb-6">
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          className="h-1 rounded-full transition-all duration-300"
          style={{
            width: i === current ? 20 : 6,
            background: i === current ? "var(--color-warm)" : "rgba(255,255,255,0.1)",
          }}
        />
      ))}
    </div>
  );
}

// ── Step: Choice ────────────────────────────────────────────
function ChoiceStep({ onIntegrate, onWhatsApp, waLink }: { onIntegrate: () => void; onWhatsApp: () => void; waLink: string }) {
  const isMobile = useIsMobile();
  const [showQR, setShowQR] = useState(false);

  return (
    <>
      <h3
        className="text-[22px] leading-[1.2] text-[var(--color-text-primary)] mb-2"
        style={{ fontFamily: "var(--font-serif)" }}
      >
        Get started with <em className="italic text-[var(--color-warm)]">Donna</em>
      </h3>
      <p className="text-[13.5px] leading-[1.6] text-[var(--color-text-muted)] font-light mb-8">
        Connect your tools so Donna can stay in the loop — or jump straight to WhatsApp.
      </p>

      <button
        onClick={onIntegrate}
        className="w-full flex items-center gap-4 p-4 rounded-xl border border-white/[0.06] bg-white/[0.02] hover:border-[var(--color-warm)]/20 hover:bg-[var(--color-warm)]/[0.03] transition-all cursor-pointer text-left mb-3 group"
      >
        <div className="w-10 h-10 rounded-xl bg-[var(--color-warm)]/10 flex items-center justify-center shrink-0">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--color-warm)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </div>
        <div>
          <p className="text-[14px] font-medium text-[var(--color-text-primary)] group-hover:text-[var(--color-warm)] transition-colors">
            Let&apos;s integrate services first
          </p>
          <p className="text-[12px] text-[var(--color-text-muted)] font-light">
            Google, Outlook, Canvas, NUSMods &amp; more
          </p>
        </div>
      </button>

      {isMobile ? (
        <button
          onClick={onWhatsApp}
          className="w-full flex items-center gap-4 p-4 rounded-xl border border-white/[0.06] bg-white/[0.02] hover:border-white/[0.1] transition-all cursor-pointer text-left group"
        >
          <div className="w-10 h-10 rounded-xl bg-white/[0.05] flex items-center justify-center shrink-0">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-white/40">
              <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
            </svg>
          </div>
          <div>
            <p className="text-[14px] font-medium text-[var(--color-text-primary)]">
              I&apos;ll use WhatsApp directly
            </p>
            <p className="text-[12px] text-[var(--color-text-muted)] font-light">
              You can always integrate later
            </p>
          </div>
        </button>
      ) : (
        <button
          onClick={() => setShowQR(true)}
          className="w-full flex items-center gap-4 p-4 rounded-xl border border-white/[0.06] bg-white/[0.02] hover:border-white/[0.1] transition-all cursor-pointer text-left group"
        >
          <div className="w-10 h-10 rounded-xl bg-white/[0.05] flex items-center justify-center shrink-0">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-white/40">
              <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
            </svg>
          </div>
          <div>
            <p className="text-[14px] font-medium text-[var(--color-text-primary)]">
              I&apos;ll use WhatsApp directly
            </p>
            <p className="text-[12px] text-[var(--color-text-muted)] font-light">
              Scan QR code to start chatting
            </p>
          </div>
        </button>
      )}

      {/* Desktop QR expand */}
      <AnimatePresence>
        {showQR && !isMobile && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="flex flex-col items-center pt-5">
              <div className="p-4 bg-white rounded-2xl">
                <QRCodeSVG
                  value={waLink}
                  size={160}
                  level="M"
                  bgColor="#ffffff"
                  fgColor="#080B0F"
                />
              </div>
              <p className="text-[12px] text-[var(--color-text-muted)] font-light mt-3">
                Scan with your phone camera to open WhatsApp
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

// ── Step: Phone ─────────────────────────────────────────────
function PhoneStep({ onNext }: { onNext: (phone: string) => void }) {
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const cleaned = phone.replace(/\D/g, "");
    if (cleaned.length < 8) {
      setError("Enter a valid phone number with country code");
      return;
    }
    onNext(cleaned);
  }

  return (
    <form onSubmit={handleSubmit}>
      <StepDots current={0} total={6} />
      <h3
        className="text-[20px] leading-[1.2] text-[var(--color-text-primary)] mb-2"
        style={{ fontFamily: "var(--font-serif)" }}
      >
        Your WhatsApp number
      </h3>
      <p className="text-[13px] leading-[1.6] text-[var(--color-text-muted)] font-light mb-6">
        We&apos;ll link your integrations to this number.
      </p>

      <div className="relative mb-2">
        <span className="absolute left-4 top-1/2 -translate-y-1/2 text-[14px] text-[var(--color-text-muted)]">+</span>
        <input
          type="tel"
          value={phone}
          onChange={(e) => { setPhone(e.target.value); setError(""); }}
          placeholder="65 8123 4567"
          className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-4 pl-7 py-3 text-[14px] text-[var(--color-text-primary)] placeholder:text-white/20 focus:outline-none focus:border-[var(--color-warm)]/30 transition-colors"
        />
      </div>
      {error && <p className="text-[12px] text-red-400/80 mb-3">{error}</p>}

      <button
        type="submit"
        className="w-full mt-4 bg-[var(--color-warm)] text-[var(--color-bg-dark)] py-3 rounded-full text-[13px] font-medium hover:-translate-y-0.5 hover:shadow-[0_6px_30px_rgba(196,149,106,0.2)] transition-all cursor-pointer"
      >
        Continue
      </button>
    </form>
  );
}

// ── Step: Google ─────────────────────────────────────────────
function GoogleStep({ phone, onNext }: { phone: string; onNext: () => void }) {
  const [connecting, setConnecting] = useState(false);

  function handleConnect() {
    setConnecting(true);
    const url = `${API_URL}/auth/google/login?user_id=${encodeURIComponent(phone)}`;
    window.open(url, "_blank", "noopener,noreferrer");
    setTimeout(() => setConnecting(false), 2000);
  }

  return (
    <>
      <StepDots current={1} total={6} />
      <div className="w-14 h-14 rounded-2xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center mb-5">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
          <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/>
          <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
          <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18A10.96 10.96 0 0 0 1 12c0 1.77.42 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
          <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
        </svg>
      </div>

      <h3 className="text-[20px] leading-[1.2] text-[var(--color-text-primary)] mb-2" style={{ fontFamily: "var(--font-serif)" }}>
        Google
      </h3>
      <p className="text-[13px] leading-[1.6] text-[var(--color-text-muted)] font-light mb-8">
        Connect Gmail and Google Calendar so Donna can read your emails and schedule.
      </p>

      <div className="flex flex-col gap-2.5">
        <button
          onClick={handleConnect}
          className="w-full py-3 rounded-full text-[13px] font-medium bg-[var(--color-warm)] text-[var(--color-bg-dark)] hover:-translate-y-0.5 hover:shadow-[0_6px_30px_rgba(196,149,106,0.2)] transition-all cursor-pointer"
        >
          {connecting ? "Opening..." : "Connect Google"}
        </button>
        <button onClick={onNext} className="w-full py-3 rounded-full text-[13px] font-light text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors cursor-pointer">
          Skip for now
        </button>
      </div>
    </>
  );
}

// ── Step: Canvas (inline token paste) ───────────────────────
function CanvasStep({ phone, onNext }: { phone: string; onNext: () => void }) {
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<"idle" | "submitting" | "success" | "error">("idle");

  async function handleSubmit() {
    if (token.length < 20) return;
    setStatus("submitting");
    try {
      const res = await fetch(`${API_URL}/onboard/canvas-token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: phone, token }),
      });
      if (res.ok) {
        setStatus("success");
        setTimeout(onNext, 800);
      } else {
        setStatus("error");
      }
    } catch {
      setStatus("error");
    }
  }

  return (
    <>
      <StepDots current={2} total={6} />
      <div className="w-14 h-14 rounded-2xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center mb-5">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
          <rect x="2" y="2" width="20" height="20" rx="4" fill="#E74C3C"/>
          <path d="M7 8h10M7 12h10M7 16h6" stroke="white" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      </div>

      <h3 className="text-[20px] leading-[1.2] text-[var(--color-text-primary)] mb-2" style={{ fontFamily: "var(--font-serif)" }}>
        Canvas LMS
      </h3>
      <p className="text-[13px] leading-[1.6] text-[var(--color-text-muted)] font-light mb-5">
        Generate an access token so Donna can track your assignments and deadlines.
      </p>

      {/* Instructions */}
      <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-4 mb-5">
        <ol className="flex flex-col gap-2.5 text-[12.5px] leading-[1.5] text-[var(--color-text-primary)]/60 font-light list-none">
          <li className="flex gap-2.5">
            <span className="text-[var(--color-warm)]/50 font-medium shrink-0">1.</span>
            Open Canvas &rarr; click your <strong className="font-medium text-[var(--color-text-primary)]/80">profile icon</strong> &rarr; <strong className="font-medium text-[var(--color-text-primary)]/80">Settings</strong>
          </li>
          <li className="flex gap-2.5">
            <span className="text-[var(--color-warm)]/50 font-medium shrink-0">2.</span>
            Scroll to <strong className="font-medium text-[var(--color-text-primary)]/80">Approved Integrations</strong> &rarr; <strong className="font-medium text-[var(--color-text-primary)]/80">+ New Access Token</strong>
          </li>
          <li className="flex gap-2.5">
            <span className="text-[var(--color-warm)]/50 font-medium shrink-0">3.</span>
            Name it <strong className="font-medium text-[var(--color-text-primary)]/80">&ldquo;Donna&rdquo;</strong>, click <strong className="font-medium text-[var(--color-text-primary)]/80">Generate Token</strong>
          </li>
          <li className="flex gap-2.5">
            <span className="text-[var(--color-warm)]/50 font-medium shrink-0">4.</span>
            Copy the token and paste it below
          </li>
        </ol>
      </div>

      <input
        type="text"
        value={token}
        onChange={(e) => { setToken(e.target.value); setStatus("idle"); }}
        placeholder="Paste your Canvas token here"
        className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-4 py-3 text-[13px] text-[var(--color-text-primary)] placeholder:text-white/20 focus:outline-none focus:border-[var(--color-warm)]/30 transition-colors font-mono mb-2"
      />
      {status === "error" && (
        <p className="text-[12px] text-red-400/80 mb-1">
          Couldn&apos;t verify that token. Check it and try again.
        </p>
      )}

      <div className="flex flex-col gap-2.5 mt-3">
        <button
          onClick={handleSubmit}
          disabled={token.length < 20 || status === "submitting"}
          className={`w-full py-3 rounded-full text-[13px] font-medium transition-all cursor-pointer ${
            token.length < 20
              ? "bg-white/[0.04] text-white/20 cursor-not-allowed"
              : status === "success"
                ? "bg-emerald-500/80 text-white"
                : "bg-[var(--color-warm)] text-[var(--color-bg-dark)] hover:-translate-y-0.5 hover:shadow-[0_6px_30px_rgba(196,149,106,0.2)]"
          }`}
        >
          {status === "submitting" ? "Verifying..." : status === "success" ? "Connected!" : "Connect Canvas"}
        </button>
        <button onClick={onNext} className="w-full py-3 rounded-full text-[13px] font-light text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors cursor-pointer">
          Skip for now
        </button>
      </div>
    </>
  );
}

// ── Step: Outlook ───────────────────────────────────────────
function OutlookStep({ phone, onNext }: { phone: string; onNext: () => void }) {
  const [connecting, setConnecting] = useState(false);

  function handleConnect() {
    setConnecting(true);
    const url = `${API_URL}/auth/microsoft/login?user_id=${encodeURIComponent(phone)}`;
    window.open(url, "_blank", "noopener,noreferrer");
    setTimeout(() => setConnecting(false), 2000);
  }

  return (
    <>
      <StepDots current={3} total={6} />
      <div className="w-14 h-14 rounded-2xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center mb-5">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
          <rect x="2" y="4" width="20" height="16" rx="3" fill="#0078D4"/>
          <path d="M2 7l10 6 10-6" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </div>

      <h3 className="text-[20px] leading-[1.2] text-[var(--color-text-primary)] mb-2" style={{ fontFamily: "var(--font-serif)" }}>
        Microsoft Outlook
      </h3>
      <p className="text-[13px] leading-[1.6] text-[var(--color-text-muted)] font-light mb-8">
        Connect Outlook email and calendar so Donna can read your NUS emails and schedule.
      </p>

      <div className="flex flex-col gap-2.5">
        <button
          onClick={handleConnect}
          className="w-full py-3 rounded-full text-[13px] font-medium bg-[var(--color-warm)] text-[var(--color-bg-dark)] hover:-translate-y-0.5 hover:shadow-[0_6px_30px_rgba(196,149,106,0.2)] transition-all cursor-pointer"
        >
          {connecting ? "Opening..." : "Connect Outlook"}
        </button>
        <button onClick={onNext} className="w-full py-3 rounded-full text-[13px] font-light text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors cursor-pointer">
          Skip for now
        </button>
      </div>
    </>
  );
}

// ── Step: NUSMods ───────────────────────────────────────────
function NUSModsStep({ phone, onNext }: { phone: string; onNext: () => void }) {
  const [url, setUrl] = useState("");
  const [status, setStatus] = useState<"idle" | "submitting" | "success" | "error">("idle");

  const isValid = url.includes("nusmods.com/timetable/");

  async function handleSubmit() {
    if (!isValid) return;
    setStatus("submitting");
    try {
      const res = await fetch(`${API_URL}/onboard/nusmods`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: phone, nusmods_url: url }),
      });
      if (res.ok) {
        setStatus("success");
        setTimeout(onNext, 800);
      } else {
        setStatus("error");
      }
    } catch {
      setStatus("error");
    }
  }

  return (
    <>
      <StepDots current={4} total={6} />
      <div className="w-14 h-14 rounded-2xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center mb-5">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
          <rect x="2" y="2" width="20" height="20" rx="4" fill="#FF6B35"/>
          <path d="M7 7h4v4H7zM13 7h4v4h-4zM7 13h4v4H7zM13 13h4v4h-4z" stroke="white" strokeWidth="1" fill="none"/>
        </svg>
      </div>

      <h3 className="text-[20px] leading-[1.2] text-[var(--color-text-primary)] mb-2" style={{ fontFamily: "var(--font-serif)" }}>
        NUSMods
      </h3>
      <p className="text-[13px] leading-[1.6] text-[var(--color-text-muted)] font-light mb-5">
        Import your timetable so Donna knows your class schedule and can plan around it.
      </p>

      <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-4 mb-5">
        <ol className="flex flex-col gap-2.5 text-[12.5px] leading-[1.5] text-[var(--color-text-primary)]/60 font-light list-none">
          <li className="flex gap-2.5">
            <span className="text-[var(--color-warm)]/50 font-medium shrink-0">1.</span>
            Go to <strong className="font-medium text-[var(--color-text-primary)]/80">nusmods.com</strong> and open your timetable
          </li>
          <li className="flex gap-2.5">
            <span className="text-[var(--color-warm)]/50 font-medium shrink-0">2.</span>
            Click <strong className="font-medium text-[var(--color-text-primary)]/80">Share/Sync</strong> at the top right
          </li>
          <li className="flex gap-2.5">
            <span className="text-[var(--color-warm)]/50 font-medium shrink-0">3.</span>
            Copy the <strong className="font-medium text-[var(--color-text-primary)]/80">share link</strong> and paste it below
          </li>
        </ol>
      </div>

      <input
        type="url"
        value={url}
        onChange={(e) => { setUrl(e.target.value); setStatus("idle"); }}
        placeholder="https://nusmods.com/timetable/sem-2/share?..."
        className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-4 py-3 text-[13px] text-[var(--color-text-primary)] placeholder:text-white/20 focus:outline-none focus:border-[var(--color-warm)]/30 transition-colors mb-2"
      />
      {status === "error" && (
        <p className="text-[12px] text-red-400/80 mb-1">
          Couldn&apos;t import that timetable. Check the URL and try again.
        </p>
      )}

      <div className="flex flex-col gap-2.5 mt-3">
        <button
          onClick={handleSubmit}
          disabled={!isValid || status === "submitting"}
          className={`w-full py-3 rounded-full text-[13px] font-medium transition-all cursor-pointer ${
            !isValid
              ? "bg-white/[0.04] text-white/20 cursor-not-allowed"
              : status === "success"
                ? "bg-emerald-500/80 text-white"
                : "bg-[var(--color-warm)] text-[var(--color-bg-dark)] hover:-translate-y-0.5 hover:shadow-[0_6px_30px_rgba(196,149,106,0.2)]"
          }`}
        >
          {status === "submitting" ? "Importing..." : status === "success" ? "Imported!" : "Import timetable"}
        </button>
        <button onClick={onNext} className="w-full py-3 rounded-full text-[13px] font-light text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors cursor-pointer">
          Skip for now
        </button>
      </div>
    </>
  );
}

// ── Step: Verify ────────────────────────────────────────────
function VerifyStep({ phone, code, onClose }: { phone: string; code: string; onClose: () => void }) {
  const waLink = `https://wa.me/${WA_NUMBER}?text=${encodeURIComponent(code)}`;
  const isMobile = useIsMobile();

  return (
    <>
      <StepDots current={5} total={6} />

      <div className="w-14 h-14 rounded-2xl bg-[var(--color-warm)]/10 flex items-center justify-center mb-5">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--color-warm)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 6L9 17l-5-5" />
        </svg>
      </div>

      <h3 className="text-[20px] leading-[1.2] text-[var(--color-text-primary)] mb-2" style={{ fontFamily: "var(--font-serif)" }}>
        One last thing
      </h3>
      <p className="text-[13px] leading-[1.6] text-[var(--color-text-muted)] font-light mb-6">
        {isMobile
          ? "Text this code to Donna on WhatsApp to verify your number and activate your account."
          : "Scan this QR code with your phone to open WhatsApp and verify your number."}
      </p>

      {isMobile ? (
        <>
          {/* Code display */}
          <div className="flex items-center justify-center mb-6">
            <div className="flex gap-2.5">
              {code.split("").map((digit, i) => (
                <div
                  key={i}
                  className="w-12 h-14 rounded-xl border border-[var(--color-warm)]/20 bg-[var(--color-warm)]/[0.04] flex items-center justify-center"
                >
                  <span className="text-[24px] font-medium text-[var(--color-warm)]" style={{ fontFamily: "var(--font-serif)" }}>
                    {digit}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <p className="text-[12px] text-center text-[var(--color-text-muted)] font-light mb-6">
            Texting <span className="text-[var(--color-text-primary)]/60 font-medium">+{phone}</span>
          </p>

          <a
            href={waLink}
            target="_blank"
            rel="noopener noreferrer"
            className="block w-full bg-[#25D366] text-white py-3 rounded-full text-[13px] font-medium text-center hover:-translate-y-0.5 hover:shadow-[0_6px_30px_rgba(37,211,102,0.2)] transition-all"
            onClick={onClose}
          >
            Open WhatsApp &amp; verify
          </a>
        </>
      ) : (
        <>
          {/* QR code for desktop */}
          <div className="flex flex-col items-center justify-center mb-6">
            <div className="p-4 bg-white rounded-2xl">
              <QRCodeSVG
                value={waLink}
                size={180}
                level="M"
                bgColor="#ffffff"
                fgColor="#080B0F"
              />
            </div>
            <p className="text-[12px] text-center text-[var(--color-text-muted)] font-light mt-4">
              Your code: <span className="text-[var(--color-warm)] font-medium tracking-widest">{code}</span>
            </p>
          </div>

          <p className="text-[12px] text-center text-[var(--color-text-muted)] font-light mb-6">
            Verifying <span className="text-[var(--color-text-primary)]/60 font-medium">+{phone}</span>
          </p>

          <a
            href={waLink}
            target="_blank"
            rel="noopener noreferrer"
            className="block w-full bg-white/[0.06] text-[var(--color-text-muted)] py-3 rounded-full text-[12px] font-light text-center hover:bg-white/[0.1] hover:text-[var(--color-text-primary)] transition-all"
            onClick={onClose}
          >
            Or open WhatsApp Web instead
          </a>
        </>
      )}
    </>
  );
}

// ── Main Modal ──────────────────────────────────────────────
export default function OnboardingModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [step, setStep] = useState<Step>("choice");
  const [phone, setPhone] = useState("");
  const [verifyCode, setVerifyCode] = useState("");

  useEffect(() => {
    if (open) {
      setStep("choice");
      setPhone("");
      setVerifyCode(generateCode());
    }
  }, [open]);

  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  const handlePhoneSubmit = useCallback((p: string) => {
    setPhone(p);
    setStep("google");
  }, []);

  const waLink = `https://wa.me/${WA_NUMBER}?text=${encodeURIComponent("Hey Donna!")}`;

  return (
    <AnimatePresence>
      {open && (
        <Overlay onClose={onClose}>
          <AnimatePresence mode="wait">
            <motion.div
              key={step}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
            >
              {step === "choice" && (
                <ChoiceStep
                  onIntegrate={() => setStep("phone")}
                  onWhatsApp={() => {
                    window.open(waLink, "_blank", "noopener,noreferrer");
                    onClose();
                  }}
                  waLink={waLink}
                />
              )}
              {step === "phone" && <PhoneStep onNext={handlePhoneSubmit} />}
              {step === "google" && <GoogleStep phone={phone} onNext={() => setStep(nextStep("google"))} />}
              {step === "canvas" && <CanvasStep phone={phone} onNext={() => setStep(nextStep("canvas"))} />}
              {step === "outlook" && <OutlookStep phone={phone} onNext={() => setStep(nextStep("outlook"))} />}
              {step === "nusmods" && <NUSModsStep phone={phone} onNext={() => setStep("verify")} />}
              {step === "verify" && <VerifyStep phone={phone} code={verifyCode} onClose={onClose} />}
            </motion.div>
          </AnimatePresence>
        </Overlay>
      )}
    </AnimatePresence>
  );
}
