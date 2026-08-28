import { useEffect } from "react";

/** Per-route document title (SEO/meta basics). */
export function useTitle(title: string): void {
  useEffect(() => {
    document.title = title;
  }, [title]);
}
