import Navbar from "@/components/Navbar";
import Hero from "@/components/Hero";
import DonnaTextsFirst from "@/components/DonnaTextsFirst";
import HowDonnaWorks from "@/components/HowDonnaWorks";
import Trust from "@/components/Trust";
import Pricing from "@/components/Pricing";
import FAQ from "@/components/FAQ";
import FinalCTA from "@/components/FinalCTA";
import Footer from "@/components/Footer";
import OnboardingProvider from "@/components/OnboardingProvider";

export default function Home() {
  return (
    <OnboardingProvider>
      <Navbar />
      <Hero />
      <DonnaTextsFirst />
      <HowDonnaWorks />
      <Trust />
      <Pricing />
      <FAQ />
      <FinalCTA />
      <Footer />
    </OnboardingProvider>
  );
}
