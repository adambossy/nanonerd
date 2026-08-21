import { useEffect, useRef, useState } from "react";
import { getSnapshotHtml } from "../api";

// Styles that live inside the shadow root alongside the source page's CSS.
// The host is a block that never widens the page; everything else is the
// source's own styling.
const SHADOW_BASE_CSS = `
:host { display: block; overflow-x: hidden; }
`;

interface RailMark {
  top: number;
  height: number;
}

interface Props {
  articleId: number;
  readIds: Set<number>;
  onMount: (root: ShadowRoot | null) => void;
  onError: (message: string) => void;
}

function stripExecutable(doc: Document): void {
  doc
    .querySelectorAll("script, iframe, object, embed, frame")
    .forEach((node) => node.remove());
  doc.querySelectorAll("*").forEach((el) => {
    for (const attr of Array.from(el.attributes)) {
      if (/^on/i.test(attr.name)) el.removeAttribute(attr.name);
    }
  });
}

/** Chromium ignores @font-face inside a shadow root, so the capture step
 *  collects them in #snapshot-fonts and we hoist that into the document. */
function hoistFonts(doc: Document, articleId: number): HTMLStyleElement | null {
  const fonts = doc.getElementById("snapshot-fonts");
  if (!fonts) return null;
  const style = document.createElement("style");
  style.dataset.snapshotFonts = String(articleId);
  style.textContent = fonts.textContent;
  fonts.remove();
  document.head.appendChild(style);
  return style;
}

function mountSnapshot(host: HTMLElement, html: string, articleId: number) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  stripExecutable(doc);
  const fontStyle = hoistFonts(doc, articleId);
  const root = host.shadowRoot ?? host.attachShadow({ mode: "open" });
  root.replaceChildren();
  const base = document.createElement("style");
  base.textContent = SHADOW_BASE_CSS;
  root.appendChild(base);
  doc.head
    .querySelectorAll("style, link[rel~=stylesheet]")
    .forEach((node) => root.appendChild(document.importNode(node, true)));
  Array.from(doc.body.childNodes).forEach((node) =>
    root.appendChild(document.importNode(node, true)),
  );
  return { root, fontStyle };
}

export function SnapshotView({ articleId, readIds, onMount, onError }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [shadow, setShadow] = useState<ShadowRoot | null>(null);
  const [marks, setMarks] = useState<RailMark[]>([]);

  useEffect(() => {
    let cancelled = false;
    let fontStyle: HTMLStyleElement | null = null;
    getSnapshotHtml(articleId)
      .then((html) => {
        if (cancelled || !hostRef.current) return;
        const mounted = mountSnapshot(hostRef.current, html, articleId);
        fontStyle = mounted.fontStyle;
        setShadow(mounted.root);
        onMount(mounted.root);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        onError(error instanceof Error ? error.message : "snapshot failed to load");
      });
    return () => {
      cancelled = true;
      fontStyle?.remove();
      hostRef.current?.shadowRoot?.replaceChildren();
      setShadow(null);
      onMount(null);
    };
    // onMount/onError are stable callbacks from the parent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [articleId]);

  // Gutter marks are drawn in an overlay beside the content instead of via
  // ::before on the blocks themselves: source CSS may position/clip blocks
  // in ways that would hide or misplace an in-element mark.
  useEffect(() => {
    const host = hostRef.current;
    if (!shadow || !host) return;
    const compute = () => {
      const hostTop = host.getBoundingClientRect().top + window.scrollY;
      const next: RailMark[] = [];
      shadow.querySelectorAll<HTMLElement>("[data-chunk-id]").forEach((el) => {
        const id = Number(el.dataset.chunkId);
        if (!readIds.has(id)) return;
        const rect = el.getBoundingClientRect();
        if (rect.height <= 0) return;
        next.push({ top: rect.top + window.scrollY - hostTop, height: rect.height });
      });
      setMarks(next);
    };
    compute();
    const observer = new ResizeObserver(compute);
    observer.observe(host);
    return () => observer.disconnect();
  }, [shadow, readIds]);

  return (
    <div className="snapshot-wrap">
      <div className="snapshot-host" ref={hostRef} />
      <div className="snapshot-rail" aria-hidden="true">
        {marks.map((mark, index) => (
          <span
            key={index}
            className="snapshot-rail-mark"
            style={{ top: mark.top, height: mark.height }}
          />
        ))}
      </div>
    </div>
  );
}
