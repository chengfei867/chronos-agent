// Play-from-start hook. Given nodes sorted by step_index, yields the index
// currently being "played" so node rendering can show a halo/pulse.
//
// Timing: 900ms per step (feels like you're watching the agent think, not a
// slideshow). Caller owns the play/pause/reset buttons and the currentIndex
// effect — we just drive the number.
import { useCallback, useEffect, useRef, useState } from "react";

const STEP_MS = 900;

export function usePlayback(totalSteps: number) {
  const [playing, setPlaying] = useState(false);
  const [index, setIndex] = useState(-1); // -1 = not started; 0..total-1 = playing/highlighting
  const timerRef = useRef<number | null>(null);

  const stop = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const play = useCallback(() => {
    if (totalSteps === 0) return;
    setIndex((i) => (i < 0 || i >= totalSteps - 1 ? 0 : i));
    setPlaying(true);
  }, [totalSteps]);

  const pause = useCallback(() => {
    setPlaying(false);
    stop();
  }, [stop]);

  const reset = useCallback(() => {
    setPlaying(false);
    setIndex(-1);
    stop();
  }, [stop]);

  useEffect(() => {
    if (!playing) return;
    if (index >= totalSteps - 1) {
      setPlaying(false);
      return;
    }
    timerRef.current = window.setTimeout(() => {
      setIndex((i) => i + 1);
    }, STEP_MS);
    return () => stop();
  }, [playing, index, totalSteps, stop]);

  useEffect(() => stop, [stop]);

  return { playing, index, totalSteps, play, pause, reset };
}
