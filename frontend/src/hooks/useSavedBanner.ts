import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

export function useSavedBanner(
  flagMap: Record<string, string>,
): [string, (next: string) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const [banner, setBanner] = useState("");

  useEffect(() => {
    let nextBanner = "";
    const matched: string[] = [];
    for (const [key, message] of Object.entries(flagMap)) {
      if (searchParams.get(key) === "ok") {
        nextBanner = message;
        matched.push(key);
      }
    }
    if (matched.length > 0) {
      setBanner(nextBanner);
      const next = new URLSearchParams(searchParams);
      for (const key of matched) next.delete(key);
      setSearchParams(next, { replace: true });
    }
    // flagMap is constructed inline by callers and changes identity per render;
    // the loop body only depends on the current key set, which is stable for a
    // given page. Reading via searchParams ensures we still react to URL changes.
  }, [searchParams, setSearchParams]);

  return [banner, setBanner];
}
