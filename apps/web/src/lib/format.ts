/** Money formatting — Indian digit grouping, paise→₹ client-side only (Rules §7.2). */

/** Branded paise type: a raw count can't be rendered as money (Rules §8.3). */
declare const PaiseBrand: unique symbol;
export type Paise = number & { readonly [PaiseBrand]: "Paise" };

export function asPaise(n: number): Paise {
  return Math.trunc(n) as Paise;
}

export function formatINR(paise: Paise): string {
  const neg = paise < 0;
  const abs = Math.abs(Math.trunc(paise));
  const rupees = Math.floor(abs / 100);
  const rest = abs % 100;
  let s = String(rupees);
  if (s.length > 3) {
    const head = s.slice(0, -3);
    const tail = s.slice(-3);
    const groups: string[] = [];
    let h = head;
    while (h.length > 2) {
      groups.unshift(h.slice(-2));
      h = h.slice(0, -2);
    }
    if (h) groups.unshift(h);
    s = [...groups, tail].join(",");
  }
  const base = rest ? `₹${s}.${String(rest).padStart(2, "0")}` : `₹${s}`;
  return neg ? `-${base}` : base;
}
