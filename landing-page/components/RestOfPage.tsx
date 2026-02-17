export default function RestOfPage() {
  return (
    <>
      <section className="min-h-[80vh] flex flex-col items-center justify-center px-6 py-20">
        <h2
          className="text-3xl md:text-4xl mb-6"
          style={{
            fontFamily: "var(--font-serif)",
            color: "var(--color-text)",
          }}
        >
          Integrations
        </h2>
        <p
          className="max-w-md text-center text-base leading-relaxed"
          style={{
            color: "var(--color-text-muted)",
            fontFamily: "var(--font-sans)",
          }}
        >
          Canvas, NUSMods, Outlook — Donna connects to the tools you already use
          and keeps everything in sync.
        </p>
      </section>

      <section className="min-h-[80vh] flex flex-col items-center justify-center px-6 py-20">
        <h2
          className="text-3xl md:text-4xl mb-6"
          style={{
            fontFamily: "var(--font-serif)",
            color: "var(--color-text)",
          }}
        >
          How It Works
        </h2>
        <p
          className="max-w-md text-center text-base leading-relaxed"
          style={{
            color: "var(--color-text-muted)",
            fontFamily: "var(--font-sans)",
          }}
        >
          Donna lives in your WhatsApp. She watches your calendar, tracks your
          deadlines, and nudges you before things slip through the cracks.
        </p>
      </section>

      <section className="min-h-[80vh] flex flex-col items-center justify-center px-6 py-20">
        <h2
          className="text-3xl md:text-4xl mb-6"
          style={{
            fontFamily: "var(--font-serif)",
            color: "var(--color-text)",
          }}
        >
          Pricing
        </h2>
        <p
          className="max-w-md text-center text-base leading-relaxed"
          style={{
            color: "var(--color-text-muted)",
            fontFamily: "var(--font-sans)",
          }}
        >
          Free during the beta. Donna is built for NUS students — no credit
          card, no catch. Just add her on WhatsApp and she&apos;s yours.
        </p>
      </section>

      <section className="min-h-[80vh] flex flex-col items-center justify-center px-6 py-20">
        <h2
          className="text-3xl md:text-4xl mb-6"
          style={{
            fontFamily: "var(--font-serif)",
            color: "var(--color-text)",
          }}
        >
          Built for NUS
        </h2>
        <p
          className="max-w-md text-center text-base leading-relaxed"
          style={{
            color: "var(--color-text-muted)",
            fontFamily: "var(--font-sans)",
          }}
        >
          Donna understands NUSMods schedules, Canvas deadlines, and the
          semester rhythm. She&apos;s not a generic AI — she&apos;s your AI.
        </p>
      </section>
    </>
  );
}
