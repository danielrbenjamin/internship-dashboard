import {useEffect, useState} from "react";

const birdPath = "M3 3C15 4 26 9 34 18C33 15 35 12 40 11C47 9 54 10 62 13C52 12 44 15 38 21L35 24C29 24 24 25 19 28L24 20C19 13 12 7 3 3Z";
const introKey = "tern.intro-seen";

export function BrandMark({animated = false}: {animated?: boolean}) {
  return <svg className="brand-mark" viewBox="0 0 64 30" aria-hidden="true">
    <path className={animated ? "brand-intro-fill" : undefined} fill="currentColor" d={birdPath} />
    {animated && <path className="brand-intro-outline" pathLength={1} d={birdPath} fill="none" />}
  </svg>;
}

export function BrandIntro() {
  const [visible, setVisible] = useState(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
    try {return sessionStorage.getItem(introKey) !== "1";}
    catch {return false;}
  });

  useEffect(() => {
    if (!visible) return;
    try {sessionStorage.setItem(introKey, "1");} catch {}
    const dismiss = () => setVisible(false);
    window.addEventListener("pointerdown", dismiss);
    window.addEventListener("keydown", dismiss);
    return () => {
      window.removeEventListener("pointerdown", dismiss);
      window.removeEventListener("keydown", dismiss);
    };
  }, [visible]);

  if (!visible) return null;
  return <div className="brand-intro" aria-hidden="true" onAnimationEnd={event => {
    if (event.target === event.currentTarget) setVisible(false);
  }}>
    <BrandMark animated />
  </div>;
}
