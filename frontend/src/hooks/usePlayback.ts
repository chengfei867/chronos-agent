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
//
// R97 (Phase 5 Arc C slice 5): added optional `initialStep` so URL deep-links
// like `#/runs/<id>/replay?step=5` can pre-seed the playback index without
// tripping the auto-play timer. If `initialStep` is in [0, totalSteps), we
// land on it on mount; otherwise -1 (not started) like before.
import { useCallback, useEffect, useRef, useState } from "react";

const STEP_MS = 900;

export interface UsePlaybackOptions {
  /** R97: pre-seed playback index (e.g. from `?step=N` URL deep-link). */
  initialStep?: number;
}

export function usePlayback(totalSteps: number, options?: UsePlaybackOptions) {
  const initialStep = options?.initialStep;
  const [playing, setPlaying] = useState(false);
  // R97: honour `initialStep` IF it's a valid index for the current totalSteps.
  // Otherwise -1 ("not started") preserves R92 behaviour. We don't clamp
  // out-of-range to N-1 silently here — Replay.tsx is responsible for that
  // policy at the URL boundary, but defensively treat negative/non-integer as
  // "ignore" to keep the hook honest if a caller passes garbage.
  const [index, setIndex] = useState<number>(() => {
    if (
      typeof initialStep === "number" &&
      Number.isInteger(initialStep) &&
      initialStep >= 0 &&
      initialStep < totalSteps
    ) {
      return initialStep;
    }
    return -1;
  });
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
