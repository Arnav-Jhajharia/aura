"use client";

import { useState, useEffect, useRef } from "react";

export interface VisitorData {
  city: string | null;
  timeString: string;
  timeCommentary: string;
  deviceLine: string;
  isLoading: boolean;
}

const defaultData: VisitorData = {
  city: null,
  timeString: "",
  timeCommentary: "",
  deviceLine: "",
  isLoading: true,
};

export function useVisitorData(): VisitorData {
  const [data, setData] = useState<VisitorData>(defaultData);
  const initRef = useRef(false);

  useEffect(() => {
    if (initRef.current) return;
    initRef.current = true;

    const now = new Date();
    const hours = now.getHours();
    const minutes = now.getMinutes();
    const h12 = hours % 12 || 12;
    const ampm = hours >= 12 ? "pm" : "am";
    const timeString = `${h12}:${minutes.toString().padStart(2, "0")}${ampm}`;

    let timeCommentary = "";
    if (hours >= 23 || hours < 5) {
      timeCommentary = "You should be asleep.";
    } else if (hours >= 5 && hours < 8) {
      timeCommentary = "Early start.";
    } else if (hours >= 8 && hours < 12) {
      timeCommentary = "Morning.";
    } else if (hours >= 18 && hours < 23) {
      timeCommentary = "Long day?";
    }

    const width = window.innerWidth;
    const isMobile = width < 768;
    const isTablet = width >= 768 && width < 1024;
    const isLateNight = hours >= 23 || hours < 4;
    const day = now.getDay();
    const isWeekend = day === 0 || day === 6;
    const dayNames = [
      "Sunday",
      "Monday",
      "Tuesday",
      "Wednesday",
      "Thursday",
      "Friday",
      "Saturday",
    ];

    let deviceLine: string;
    if (isWeekend) {
      deviceLine = `It's ${dayNames[day]}. No class today.`;
    } else if (isLateNight && isMobile) {
      deviceLine = "You're in bed scrolling.";
    } else if (isMobile) {
      deviceLine = "You're on your phone.";
    } else if (isTablet) {
      deviceLine = "You're on your tablet.";
    } else {
      deviceLine = "You're at your desk.";
    }

    setData((prev) => ({
      ...prev,
      timeString,
      timeCommentary,
      deviceLine,
    }));

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 2000);

    fetch("https://ipapi.co/json/", { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error("API error");
        return res.json();
      })
      .then((json) => {
        setData((prev) => ({
          ...prev,
          city: json.city || null,
          isLoading: false,
        }));
      })
      .catch(() => {
        setData((prev) => ({ ...prev, isLoading: false }));
      })
      .finally(() => {
        clearTimeout(timeout);
      });

    return () => {
      clearTimeout(timeout);
      controller.abort();
    };
  }, []);

  return data;
}
