import Navbar from "@/components/Navbar";
import Hero from "@/components/Hero";
import Integrations from "@/components/Integrations";
import HowItWorks from "@/components/HowItWorks";
import Features from "@/components/Features";
import Testimonials from "@/components/Testimonials";
import Pricing from "@/components/Pricing";
import FAQ from "@/components/FAQ";
import FinalCTA from "@/components/FinalCTA";
import Footer from "@/components/Footer";

export default function Home() {
  return (
    <>
      <Navbar />
      <Hero />
      <Integrations />
      <HowItWorks />
      <Features />
      <Testimonials />
      <Pricing />
      <FAQ />
      <FinalCTA />
      <Footer />
    </>
  );
}
