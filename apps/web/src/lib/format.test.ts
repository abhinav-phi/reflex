import { describe, expect, it } from "vitest";
import { asPaise, formatINR } from "./format";

describe("formatINR (Rules §7.2 Indian grouping)", () => {
  it("formats ₹2,41,000 from paise", () => {
    expect(formatINR(asPaise(24100000))).toBe("₹2,41,000");
  });
  it("formats plain rupees", () => {
    expect(formatINR(asPaise(29900))).toBe("₹299");
  });
  it("keeps paise", () => {
    expect(formatINR(asPaise(150))).toBe("₹1.50");
  });
  it("zero", () => {
    expect(formatINR(asPaise(0))).toBe("₹0");
  });
  it("negative", () => {
    expect(formatINR(asPaise(-150))).toBe("-₹1.50");
  });
});
