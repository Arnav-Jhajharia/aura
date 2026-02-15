"use client";

const LINKS = {
  Product: ["How it works", "Integrations", "Pricing", "Security"],
  Company: ["About", "Blog", "GitHub", "Press"],
  Legal: ["Privacy", "Terms", "Security"],
};

const LINK_HREFS: Record<string, string> = {
  "How it works": "#how-donna-works",
  Integrations: "#how-donna-works",
  Pricing: "#pricing",
  Security: "#trust",
  GitHub: "https://github.com/Arnav-Jhajharia/aura",
};

export default function Footer() {
  return (
    <footer className="relative w-full px-6 pt-16 pb-10">
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-[200px] h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent, rgba(196,149,106,0.2), transparent)",
        }}
      />

      <div className="max-w-[960px] mx-auto">
        <div className="flex flex-col md:flex-row justify-between gap-12 mb-16">
          {/* Brand */}
          <div className="max-w-[260px]">
            <a
              href="#"
              className="text-[22px] text-[var(--color-warm)] block mb-3"
              style={{ fontFamily: "var(--font-serif)" }}
            >
              donna
            </a>
            <p className="text-[13px] leading-[1.6] text-[var(--color-text-muted)] font-light">
              Your second brain on WhatsApp. Share your life — she remembers.
            </p>
          </div>

          {/* Link columns */}
          <div className="flex gap-10 md:gap-16 flex-wrap">
            {Object.entries(LINKS).map(([heading, items]) => (
              <div key={heading}>
                <h4 className="text-[11px] uppercase tracking-[2px] text-[var(--color-text-muted)] font-medium mb-4">
                  {heading}
                </h4>
                <ul className="flex flex-col gap-2.5">
                  {items.map((item) => (
                    <li key={item}>
                      <a
                        href={LINK_HREFS[item] || "#"}
                        {...(LINK_HREFS[item]?.startsWith("http") ? { target: "_blank", rel: "noopener noreferrer" } : {})}
                        className="text-[13px] text-[var(--color-text-primary)]/50 hover:text-[var(--color-text-primary)] transition-colors font-light"
                      >
                        {item}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        {/* Bottom bar */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-8 border-t border-white/[0.05]">
          <p className="text-[11px] text-[var(--color-text-dim)] font-light">
            &copy; {new Date().getFullYear()} Donna. All rights reserved.
          </p>
          <div className="flex items-center gap-5">
            {/* Twitter/X */}
            <a
              href="#"
              className="text-[var(--color-text-dim)] hover:text-[var(--color-warm)] transition-colors"
              aria-label="Twitter"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
              </svg>
            </a>
            {/* LinkedIn */}
            <a
              href="#"
              className="text-[var(--color-text-dim)] hover:text-[var(--color-warm)] transition-colors"
              aria-label="LinkedIn"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
              </svg>
            </a>
            {/* GitHub */}
            <a
              href="https://github.com/Arnav-Jhajharia/aura"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--color-text-dim)] hover:text-[var(--color-warm)] transition-colors"
              aria-label="GitHub"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
              </svg>
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
