import { useEffect, useRef, useState } from "react";

/**
 * the app's primary two-pane shell. desktop: sticky left rail + scrollable
 * canvas. mobile: the rail becomes an off-canvas drawer driven by the topbar
 * hamburger (a global "spotter:toggle-nav" event) plus a backdrop scrim.
 */
export default function Board({ rail, children, className = "" }) {
  const [open, setOpen] = useState(false);
  const railRef = useRef(null);

  useEffect(() => {
    function onToggle(e) {
      setOpen((o) => !o);
      e?.preventDefault?.();
    }
    window.addEventListener("spotter:toggle-nav", onToggle);
    return () => window.removeEventListener("spotter:toggle-nav", onToggle);
  }, []);

  useEffect(() => {
    if (!open) return;
    function onKey(e) {
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className={`shell ${className}`}>
      <div
        className={`nav-scrim ${open ? "show" : ""}`}
        onClick={() => setOpen(false)}
        aria-hidden={!open}
      />
      <aside ref={railRef} className={`rail ${open ? "rail-open" : ""}`} aria-label="Sidebar">
        {rail}
      </aside>
      <main className="canvas" id="main">
        {children}
      </main>
    </div>
  );
}