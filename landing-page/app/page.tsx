"use client";

import { useState } from "react";
import Hero from "@/components/Hero";
import Navbar from "@/components/Navbar";
import RestOfPage from "@/components/RestOfPage";

export default function Home() {
  const [heroComplete, setHeroComplete] = useState(false);

  return (
    <>
      <Navbar visible={heroComplete} />
      <Hero onComplete={() => setHeroComplete(true)} />
      <RestOfPage />
    </>
  );
}
