"use client";

import { useRef, useEffect } from "react";
import { useOnboarding } from "./OnboardingProvider";

function useScrollUnderline() {
  const pathRef = useRef<SVGPathElement>(null);

  useEffect(() => {
    const path = pathRef.current;
    if (!path) return;

    const totalLength = path.getTotalLength();
    path.style.strokeDasharray = `${totalLength}`;
    path.style.strokeDashoffset = `${totalLength}`;

    function onScroll() {
      const progress = Math.min(1, window.scrollY / 300);
      path!.style.strokeDashoffset = `${totalLength * (1 - progress)}`;
    }

    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();

    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return pathRef;
}

// --- Step 1: Thought text pool + Fragment type ---
const THOUGHT_TEXTS = [
  "rent??", "gym 7am", "call mom", "deadline fri", "groceries",
  "dentist tue", "reply to Jake", "book flights", "water plants",
  "submit report", "pick up meds", "lunch w/ Sara", "oil change",
  "birthday gift", "pay electric", "read ch. 4", "cancel sub",
  "backup photos", "team sync 3pm", "buy milk", "fix bike",
  "email prof", "laundry", "renew passport", "return package",
  "yoga 6pm", "call plumber", "update resume", "clean fridge",
  "vet appt", "send invoice", "buy charger",
];

interface Fragment {
  x: number;
  baseY: number;
  vx: number;
  wobbleAmp: number;
  wobbleFreq: number;
  wobblePhase: number;
  rotation: number;
  baseOpacity: number;
  scale: number;
  waveTarget: number;
  cacheIndex: number;
}

// Each component wave = a "thread" of your life
const WAVES = [
  { freq: 0.003, amp: 30, speed: 0.4,  phase: 0,   color: [196, 149, 106] as const, label: "calendar" },
  { freq: 0.005, amp: 22, speed: 0.55, phase: 1.3, color: [206, 169, 136] as const, label: "deadlines" },
  { freq: 0.008, amp: 15, speed: 0.75, phase: 2.7, color: [176, 149, 126] as const, label: "ideas" },
  { freq: 0.013, amp: 10, speed: 1.0,  phase: 0.8, color: [186, 139, 116] as const, label: "reminders" },
  { freq: 0.021, amp: 6,  speed: 1.4,  phase: 3.5, color: [166, 159, 136] as const, label: "messages" },
];

export default function Hero() {
  const heroRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pathRef = useScrollUnderline();
  const openOnboarding = useOnboarding();

  useEffect(() => {
    const hero = heroRef.current!;
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d")!;
    let W = 0, H = 0;
    let lastTime = 0;

    // --- Step 2: Pill cache ---
    let pillCache: HTMLCanvasElement[] = [];

    function buildPillCache() {
      pillCache = THOUGHT_TEXTS.map((text) => {
        const offscreen = document.createElement("canvas");
        const oc = offscreen.getContext("2d")!;
        const dpr = window.devicePixelRatio || 1;

        oc.font = "500 11px 'DM Sans', sans-serif";
        const metrics = oc.measureText(text);
        const textW = metrics.width;
        const pillH = 24;
        const hPad = 9;
        const pillW = textW + hPad * 2;

        offscreen.width = Math.ceil(pillW * dpr);
        offscreen.height = Math.ceil(pillH * dpr);
        oc.scale(dpr, dpr);

        // Rounded rect fill
        const r = pillH / 2;
        oc.beginPath();
        oc.moveTo(r, 0);
        oc.lineTo(pillW - r, 0);
        oc.arc(pillW - r, r, r, -Math.PI / 2, Math.PI / 2);
        oc.lineTo(r, pillH);
        oc.arc(r, r, r, Math.PI / 2, -Math.PI / 2);
        oc.closePath();
        oc.fillStyle = "rgba(196,149,106,0.12)";
        oc.fill();

        // Text
        oc.font = "500 11px 'DM Sans', sans-serif";
        oc.textAlign = "center";
        oc.textBaseline = "middle";
        oc.fillStyle = "rgba(196,149,106,0.85)";
        oc.fillText(text, pillW / 2, pillH / 2);

        return offscreen;
      });
    }

    // --- Step 3: Fragment pool ---
    let fragments: Fragment[] = [];
    let fragmentCount = 45;

    function randRange(min: number, max: number) {
      return min + Math.random() * (max - min);
    }

    function initFragment(staggerX?: number): Fragment {
      const isMobile = W < 768;
      return {
        x: staggerX !== undefined ? staggerX : randRange(-80, 0),
        baseY: randRange(H * 0.1, H * 0.9),
        vx: isMobile ? randRange(25, 50) : randRange(18, 40),
        wobbleAmp: randRange(8, 28),
        wobbleFreq: randRange(0.4, 1.2),
        wobblePhase: Math.random() * Math.PI * 2,
        rotation: randRange(-0.35, 0.35),
        baseOpacity: randRange(0.08, 0.22),
        scale: randRange(0.7, 1.3),
        waveTarget: Math.floor(Math.random() * WAVES.length),
        cacheIndex: Math.floor(Math.random() * THOUGHT_TEXTS.length),
      };
    }

    function initFragments() {
      fragmentCount = W < 768 ? 25 : 45;
      fragments = [];
      for (let i = 0; i < fragmentCount; i++) {
        fragments.push(initFragment(randRange(-80, W * 0.5)));
      }
    }

    function resize() {
      const dpr = window.devicePixelRatio || 1;
      W = hero.offsetWidth;
      H = hero.offsetHeight;
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      canvas.style.width = W + "px";
      canvas.style.height = H + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      buildPillCache();
      initFragments();
    }
    resize();
    window.addEventListener("resize", resize);

    function waveY(wave: (typeof WAVES)[number], x: number, time: number) {
      const ampMod = 1 + 0.15 * Math.sin(time * 0.3 + wave.phase);
      return Math.sin(x * wave.freq - time * wave.speed + wave.phase) * wave.amp * ampMod;
    }

    function loop(now: number) {
      const time = now / 1000;
      const dt = lastTime === 0 ? 0.016 : Math.min((now - lastTime) / 1000, 0.05);
      lastTime = now;

      ctx.clearRect(0, 0, W, H);

      const centerY = H / 2;
      const numWaves = WAVES.length;
      const maxSpread = H * 0.4;

      // --- Step 4 & 5: Update & render fragments (BEFORE waves) ---
      for (let i = 0; i < fragments.length; i++) {
        const f = fragments[i];

        // Physics update
        f.x += f.vx * dt;

        const nx = f.x / W; // normalized x [0..1]

        // Vertical wobble
        let currentY = f.baseY + Math.sin(time * f.wobbleFreq + f.wobblePhase) * f.wobbleAmp;
        let currentRotation = f.rotation;

        // Transition zone (>30%): attraction toward wave lane
        if (nx > 0.3) {
          const t = Math.min(1, (nx - 0.3) / 0.35); // 0→1 across transition
          const ease = t * t;

          // Dampen wobble
          const dampedAmp = f.wobbleAmp * (1 - ease * 0.9);
          currentY = f.baseY + Math.sin(time * f.wobbleFreq + f.wobblePhase) * dampedAmp;

          // Decay rotation
          currentRotation = f.rotation * (1 - ease);

          // Attract baseY toward wave target lane
          const wi = f.waveTarget;
          const normalizedOffset = (wi - (numWaves - 1) / 2) / ((numWaves - 1) / 2);
          const spreadTarget = normalizedOffset * maxSpread / 2;
          const waveTargetY = centerY + spreadTarget * ((f.x / W) ** 2) + waveY(WAVES[wi], f.x, time);
          f.baseY += (waveTargetY - f.baseY) * ease * 0.08;
        }

        // Recycle when past 65%
        if (f.x > W * 0.65) {
          fragments[i] = initFragment();
          continue;
        }

        // Compute opacity
        let opacity = f.baseOpacity;

        // Fade-in from left edge
        if (f.x < 40) {
          opacity *= Math.max(0, f.x / 40);
        }

        // Quadratic fade-out through transition zone
        if (nx > 0.3) {
          const t = (nx - 0.3) / 0.35;
          opacity *= Math.max(0, 1 - t * t);
        }

        // Edge-fade near top/bottom
        const edgeDist = Math.min(currentY, H - currentY);
        if (edgeDist < 60) {
          opacity *= Math.max(0, edgeDist / 60);
        }

        if (opacity < 0.005) continue;

        // Render pill
        const pill = pillCache[f.cacheIndex];
        if (!pill) continue;

        const dpr = window.devicePixelRatio || 1;
        const drawW = pill.width / dpr;
        const drawH = pill.height / dpr;

        ctx.save();
        ctx.globalAlpha = opacity;
        ctx.translate(f.x, currentY);
        ctx.rotate(currentRotation);
        ctx.scale(f.scale, f.scale);
        ctx.drawImage(pill, -drawW / 2, -drawH / 2, drawW, drawH);
        ctx.restore();
      }

      ctx.globalAlpha = 1;

      // --- Step 6: Composite waveform (modified gradient) ---
      const compGrad = ctx.createLinearGradient(0, 0, W, 0);
      compGrad.addColorStop(0, "rgba(196,149,106,0.0)");
      compGrad.addColorStop(0.2, "rgba(196,149,106,0.04)");
      compGrad.addColorStop(0.4, "rgba(196,149,106,0.14)");
      compGrad.addColorStop(0.55, "rgba(196,149,106,0.06)");
      compGrad.addColorStop(0.75, "rgba(196,149,106,0.0)");

      ctx.beginPath();
      for (let x = 0; x <= W; x += 2) {
        let y = centerY;
        for (const wave of WAVES) y += waveY(wave, x, time);
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = compGrad;
      ctx.lineWidth = 2;
      ctx.stroke();

      // --- Individual decomposed waves (modified gradient) ---
      for (let wi = 0; wi < numWaves; wi++) {
        const wave = WAVES[wi];
        const normalizedOffset = (wi - (numWaves - 1) / 2) / ((numWaves - 1) / 2);
        const spreadTarget = normalizedOffset * maxSpread / 2;

        const [r, g, b] = wave.color;

        // Step 6: Individual wave gradient — invisible left, emerging through transition
        const grad = ctx.createLinearGradient(0, 0, W, 0);
        grad.addColorStop(0, `rgba(${r},${g},${b},0.0)`);
        grad.addColorStop(0.25, `rgba(${r},${g},${b},0.0)`);
        grad.addColorStop(0.4, `rgba(${r},${g},${b},0.06)`);
        grad.addColorStop(0.55, `rgba(${r},${g},${b},0.14)`);
        grad.addColorStop(0.75, `rgba(${r},${g},${b},0.22)`);
        grad.addColorStop(1, `rgba(${r},${g},${b},0.28)`);

        ctx.beginPath();
        for (let x = 0; x <= W; x += 2) {
          const sep = (x / W) ** 2;
          const yOffset = spreadTarget * sep;
          const y = centerY + yOffset + waveY(wave, x, time);
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = grad;

        // Soft glow pass
        ctx.lineWidth = 6;
        ctx.globalAlpha = 0.3;
        ctx.stroke();

        // Crisp line pass
        ctx.lineWidth = 1.5;
        ctx.globalAlpha = 1;
        ctx.stroke();

        // Step 7: Bloom glow pass on right-side waves
        const bloomGrad = ctx.createLinearGradient(0, 0, W, 0);
        bloomGrad.addColorStop(0, `rgba(${r},${g},${b},0.0)`);
        bloomGrad.addColorStop(0.6, `rgba(${r},${g},${b},0.0)`);
        bloomGrad.addColorStop(0.8, `rgba(${r},${g},${b},0.06)`);
        bloomGrad.addColorStop(1, `rgba(${r},${g},${b},0.10)`);
        ctx.strokeStyle = bloomGrad;
        ctx.lineWidth = 12;
        ctx.globalAlpha = 1;
        ctx.stroke();

        ctx.globalAlpha = 1;

        // Label at the right edge, hugging the wave
        const labelX = W - 14;
        const labelY = centerY + spreadTarget + waveY(wave, W, time);
        ctx.font = "500 9px 'DM Sans', sans-serif";
        ctx.letterSpacing = "2px";
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        ctx.fillStyle = `rgba(${r},${g},${b},0.3)`;
        ctx.fillText(wave.label.toUpperCase(), labelX, labelY);
        ctx.letterSpacing = "0px";
      }

      requestAnimationFrame(loop);
    }

    requestAnimationFrame(loop);

    return () => window.removeEventListener("resize", resize);
  }, []);

  return (
    <section ref={heroRef} className="relative w-full h-screen overflow-hidden">
      {/* Depth gradient */}
      <div className="absolute inset-0 z-0 pointer-events-none"
        style={{ background: "linear-gradient(to bottom, rgba(12,16,22,0) 0%, rgba(5,7,10,0.5) 60%, rgba(3,4,6,0.9) 100%)" }}
      />

      <canvas ref={canvasRef} className="absolute inset-0 z-[1]" />

      {/* Content */}
      <div className="absolute inset-0 z-10 flex flex-col items-center justify-center pointer-events-none">
        <div className="text-center max-w-[660px] px-6 pointer-events-auto relative">
          {/* Radial bg for readability */}
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[min(700px,95vw)] h-[480px] pointer-events-none -z-10"
            style={{ background: "radial-gradient(ellipse, rgba(8,11,15,0.93) 0%, rgba(8,11,15,0.6) 40%, transparent 68%)" }}
          />

          <p className="text-[10px] uppercase tracking-[4px] text-[var(--color-warm)] font-medium mb-7 animate-[fadeUp_1.2s_ease-out_0.3s_both]">
            your second brain on whatsapp
          </p>

          <h1
            className="font-normal leading-[1.08] tracking-[-0.02em] text-[var(--color-text-primary)] mb-6 animate-[fadeUp_1.2s_ease-out_0.5s_both]"
            style={{ fontFamily: "var(--font-serif)", fontSize: "clamp(44px, 6.5vw, 80px)" }}
          >
            You forget.<br />
            <em className="italic text-[var(--color-warm)]">
              Donna{" "}
              <span className="cursive-underline">
                doesn&apos;t.
                <svg
                  className="cursive-underline-svg"
                  viewBox="0 0 300 8"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    ref={pathRef}
                    d="M1 4.5C50 2.5 100 6.5 150 4C200 1.5 250 6 299 3.5"
                    stroke="#C4956A"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    opacity="0.55"
                  />
                </svg>
              </span>
            </em>
          </h1>

          <p className="text-[16px] leading-[1.7] text-[var(--color-text-muted)] font-light max-w-[430px] mx-auto mb-10 animate-[fadeUp_1.2s_ease-out_0.7s_both]">
            Every passing thought sinks into the noise of life. Donna catches them all — and surfaces the right one, right when you need it.
          </p>

          <div className="animate-[fadeUp_1.2s_ease-out_0.9s_both]">
            <button
              onClick={openOnboarding}
              className="bg-[var(--color-warm)] text-[var(--color-bg-dark)] px-9 py-3.5 rounded-full text-[14px] font-medium tracking-[0.01em] hover:-translate-y-0.5 hover:shadow-[0_6px_30px_rgba(196,149,106,0.25)] transition-all cursor-pointer"
            >
              Try Donna
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
