import type { BrandVariants } from "@fluentui/react-components";

const STEPS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160] as const;

function hslToHex(h: number, s: number, l: number): string {
  const sat = s / 100;
  const lig = l / 100;
  const a = sat * Math.min(lig, 1 - lig);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    const v = lig - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return Math.round(v * 255)
      .toString(16)
      .padStart(2, "0");
  };
  return "#" + f(0) + f(8) + f(4);
}

/**
 * Builds a 16-step Fluent brand ramp from a hue (0-359) and saturation (0-100).
 * Lets packs express colour as data without hex literals outside tokens/.
 */
export function rampFromHue(hue: number, saturation: number): BrandVariants {
  const ramp: Partial<Record<(typeof STEPS)[number], string>> = {};
  STEPS.forEach((step, i) => {
    const lightness = 4 + Math.pow(i / (STEPS.length - 1), 0.7) * 93;
    ramp[step] = hslToHex(hue, saturation, lightness);
  });
  return ramp as BrandVariants;
}
