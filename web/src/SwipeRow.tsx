import {
  useCallback,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
} from "react";

/** Horizontal distance (as a fraction of row width) past which a swipe commits. */
const COMMIT_FRACTION = 0.35;
/** Pointer must move this far before we decide whether it's a horizontal swipe or a vertical scroll. */
const AXIS_LOCK_PX = 8;
/** Icon scale while dragging: grows from MIN toward MAX as the finger approaches the threshold... */
const ICON_SCALE_MIN = 0.8;
const ICON_SCALE_MAX = 1.45;
/** ...then snaps down to this settled size once the swipe commits. */
const ICON_SCALE_SETTLED = 1.1;
const LEAVE_MS = 220;

type Side = "left" | "right";

interface SwipeRowProps {
  children: ReactNode;
  /** Revealed on the left edge while swiping right. */
  rightSwipeIcon: ReactNode;
  /** Revealed on the right edge while swiping left. */
  leftSwipeIcon: ReactNode;
  /** Called after the row has animated off-screen. If the returned promise settles and the row
   *  is still mounted (e.g. the request failed and the list refreshed it back in), the row springs back. */
  onSwipeRight: () => void | Promise<void>;
  onSwipeLeft: () => void | Promise<void>;
}

export default function SwipeRow({
  children,
  rightSwipeIcon,
  leftSwipeIcon,
  onSwipeRight,
  onSwipeLeft,
}: SwipeRowProps) {
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [leaving, setLeaving] = useState<Side | null>(null);

  const rowRef = useRef<HTMLDivElement>(null);
  const startRef = useRef({ x: 0, y: 0 });
  const axisRef = useRef<"x" | "y" | null>(null);
  const movedRef = useRef(false);

  const width = rowRef.current?.offsetWidth ?? 0;
  const threshold = width * COMMIT_FRACTION;
  const committed = threshold > 0 && Math.abs(dx) >= threshold;
  const side: Side | null = dx > 0 ? "right" : dx < 0 ? "left" : null;
  const progress = threshold > 0 ? Math.min(Math.abs(dx) / threshold, 1) : 0;
  const iconScale = committed
    ? ICON_SCALE_SETTLED
    : ICON_SCALE_MIN + (ICON_SCALE_MAX - ICON_SCALE_MIN) * progress;

  const reset = useCallback(() => {
    axisRef.current = null;
    setDragging(false);
    setDx(0);
  }, []);

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (leaving || event.button !== 0) return;
    startRef.current = { x: event.clientX, y: event.clientY };
    axisRef.current = null;
    movedRef.current = false;
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (leaving || event.buttons === 0) return;
    const moveX = event.clientX - startRef.current.x;
    const moveY = event.clientY - startRef.current.y;

    if (axisRef.current === null) {
      if (Math.abs(moveX) < AXIS_LOCK_PX && Math.abs(moveY) < AXIS_LOCK_PX) return;
      axisRef.current = Math.abs(moveX) > Math.abs(moveY) ? "x" : "y";
      if (axisRef.current === "x") {
        event.currentTarget.setPointerCapture(event.pointerId);
        setDragging(true);
      }
    }
    if (axisRef.current !== "x") return;

    movedRef.current = true;
    setDx(moveX);
  };

  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    if (axisRef.current !== "x") {
      axisRef.current = null;
      return;
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (committed && side) {
      setLeaving(side);
      setDragging(false);
      setDx(side === "right" ? width : -width);
      window.setTimeout(() => {
        const result = side === "right" ? onSwipeRight() : onSwipeLeft();
        void Promise.resolve(result).finally(() => {
          // No-op if the row unmounted (success); restores it if it's still here (failure).
          setLeaving(null);
          setDx(0);
        });
      }, LEAVE_MS);
      return;
    }
    reset();
  };

  // A drag must not also fire the card's click-through navigation.
  const onClickCapture = (event: MouseEvent<HTMLDivElement>) => {
    if (movedRef.current) {
      event.preventDefault();
      event.stopPropagation();
      movedRef.current = false;
    }
  };

  const bgClass =
    side === "right" ? "swipe-bg swipe-bg-archive" : "swipe-bg swipe-bg-delete";

  return (
    <div
      ref={rowRef}
      className={`swipe-row${dragging ? " is-dragging" : ""}${committed ? " is-committed" : ""}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={reset}
      onClickCapture={onClickCapture}
      // Cards are <a> elements; a mouse drag would otherwise start a native link drag and cancel the gesture.
      onDragStart={(event) => event.preventDefault()}
    >
      {side && (
        <div className={bgClass} aria-hidden="true">
          <span className="swipe-icon" style={{ transform: `scale(${iconScale})` }}>
            {side === "right" ? rightSwipeIcon : leftSwipeIcon}
          </span>
        </div>
      )}
      <div
        className="swipe-fg"
        style={{
          transform: `translateX(${dx}px)`,
          transition: dragging ? "none" : `transform ${LEAVE_MS}ms ease-out`,
        }}
      >
        {children}
      </div>
    </div>
  );
}
