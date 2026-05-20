// Play-from-start hook. Given nodes sorted by step_index, yields the index
// currently being "played" so node rendering can show a halo/pulse.
//
// Timing: 900ms per step (feels like you're watching the agent think, not a
// slideshow). Caller owns the play/pause/reset buttons and the currentIndex
// effect — we just drive the number.
//
// R92 (Phase 5 Arc C slice 1): added stepBack/stepForward/jumpTo so linear
// Replay UI can reuse this hook for keyboard nav (←/→/Space/q) and
// click-to-jump on PlaybackTimeline. Backward compatible — TreeView keeps
// using {playing, index, play, pause, reset} unchanged.
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

  // R92: explicit step controls for keyboard nav. Pause first so the auto-play
  // timer doesn't fight a manual step.
  const stepForward = useCallback(() => {
    if (totalSteps === 0) return;
    setPlaying(false);
    stop();
    setIndex((i) => {
      const next = i < 0 ? 0 : i + 1;
      return next >= totalSteps ? totalSteps - 1 : next;
    });
  }, [totalSteps, stop]);

  const stepBack = useCallback(() => {
    if (totalSteps === 0) return;
    setPlaying(false);
    stop();
    setIndex((i) => {
      if (i <= 0) return 0;
      return i - 1;
    });
  }, [totalSteps, stop]);

  // R92: click-to-jump on the timeline. Clamps and pauses.
  const jumpTo = useCallback(
    (target: number) => {
      if (totalSteps === 0) return;
      setPlaying(false);
      stop();
      const clamped = Math.max(0, Math.min(totalSteps - 1, Math.floor(target)));
      setIndex(clamped);
    },
    [totalSteps, stop],
  );

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

  return {
    playing,
    index,
    totalSteps,
    play,
    pause,
    reset,
    stepForward,
    stepBack,
    jumpTo,
  };
}
