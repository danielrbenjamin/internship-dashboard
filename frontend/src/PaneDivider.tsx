import {useRef, type KeyboardEvent, type PointerEvent} from "react";

export function PaneDivider({label, value, min, max, direction, onResize}: {
  label: string; value: number; min: number; max: number; direction: 1 | -1;
  onResize: (width: number) => void;
}) {
  const drag = useRef<{x: number; width: number} | null>(null);
  const resize = (width: number) => onResize(Math.round(Math.max(min, Math.min(max, width))));

  function start(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.focus();
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.dataset.dragging = "true";
    drag.current = {x: event.clientX, width: value};
  }

  function finish(event: PointerEvent<HTMLDivElement>) {
    drag.current = null;
    delete event.currentTarget.dataset.dragging;
  }

  function keyboard(event: KeyboardEvent<HTMLDivElement>) {
    const delta = event.key === "ArrowLeft" ? -1 : event.key === "ArrowRight" ? 1 : 0;
    if (!delta && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    resize(event.key === "Home" ? min : event.key === "End" ? max : value + delta * direction * 20);
  }

  return <div className="pane-divider" role="separator" tabIndex={0} aria-orientation="vertical"
    aria-label={label} aria-valuemin={min} aria-valuemax={max} aria-valuenow={value}
    onPointerDown={start} onLostPointerCapture={finish} onKeyDown={keyboard}
    onPointerMove={event => {if (drag.current) resize(drag.current.width + direction * (event.clientX - drag.current.x));}} />;
}
