// In-page serializer for snapshot capture. Runs inside the rendered page after
// load; mutates the live DOM (we discard the page afterwards) and returns the
// post-JS HTML. Stylesheets are read through CSSOM where same-origin allows it
// (this also flattens @import and absolutizes url()); otherwise the <link> is
// marked `data-sf-unresolved` for the Python side to fill from harvested
// network responses. No scripts survive.
async () => {
  const doc = document;
  const abs = (value) => {
    try {
      return new URL(value, doc.baseURI).href;
    } catch {
      return value;
    }
  };

  const mediaMatches = (media) => {
    if (!media || media.trim() === "" || media.trim() === "all") return true;
    try {
      return matchMedia(media).matches;
    } catch {
      return true;
    }
  };

  // 1. Stylesheets -> inline <style>.
  for (const link of [...doc.querySelectorAll('link[rel~="stylesheet"]')]) {
    const href = link.href;
    if (!mediaMatches(link.media) || /print/i.test(link.media || "")) {
      link.remove();
      continue;
    }
    let text = null;
    let base = abs(href);
    try {
      const sheet = link.sheet;
      if (sheet) text = [...sheet.cssRules].map((rule) => rule.cssText).join("\n");
    } catch {
      text = null;
    }
    if (text === null) {
      try {
        const response = await fetch(href, { mode: "cors", credentials: "omit" });
        if (response.ok) text = await response.text();
      } catch {
        text = null;
      }
    }
    if (text === null) {
      link.setAttribute("data-sf-unresolved", base);
      continue;
    }
    const style = doc.createElement("style");
    style.textContent = text;
    style.setAttribute("data-sf-base", base);
    link.replaceWith(style);
  }
  for (const style of doc.querySelectorAll("style")) {
    if (!style.hasAttribute("data-sf-base")) style.setAttribute("data-sf-base", doc.baseURI);
    if (style.media && !mediaMatches(style.media)) style.remove();
  }

  // 2. Images: freeze the chosen candidate, drop lazy-load machinery.
  for (const img of doc.querySelectorAll("img")) {
    const chosen = img.currentSrc || img.getAttribute("data-src") || img.getAttribute("data-lazy-src");
    if (chosen) img.setAttribute("src", abs(chosen));
    for (const attr of ["srcset", "sizes", "loading", "decoding", "data-src", "data-srcset", "data-lazy-src"]) {
      img.removeAttribute(attr);
    }
  }
  for (const source of doc.querySelectorAll("picture > source")) source.remove();
  for (const video of doc.querySelectorAll("video")) {
    video.removeAttribute("autoplay");
    if (video.poster) video.setAttribute("poster", abs(video.poster));
  }

  // 3. Absolutize navigation/resource URLs.
  for (const anchor of doc.querySelectorAll("a[href]")) {
    const raw = anchor.getAttribute("href") || "";
    if (raw.startsWith("#") || /^\s*javascript:/i.test(raw)) continue;
    anchor.setAttribute("href", abs(raw));
  }
  for (const el of doc.querySelectorAll("[src]")) {
    const raw = el.getAttribute("src") || "";
    if (raw && !raw.startsWith("data:") && !raw.startsWith("blob:")) el.setAttribute("src", abs(raw));
  }

  // 4. Remove executable / non-renderable nodes, anything display:none, and
  //    fixed overlays (drawers, cookie bars, sticky headers). Sticky elements
  //    keep their content but lose the stickiness.
  const hidden = [];
  const fixed = [];
  let scroller = null;
  for (const el of doc.body ? doc.body.querySelectorAll("*") : []) {
    if (el.closest("svg") || el.tagName === "STYLE" || el.tagName === "LINK") continue;
    let style = null;
    try {
      style = getComputedStyle(el);
    } catch {
      continue;
    }
    if (style.display === "none") {
      hidden.push(el);
      continue;
    }
    if (style.position === "fixed") {
      fixed.push(el);
    } else if (style.position === "sticky") {
      el.style.setProperty("position", "static", "important");
    }
    // App-shell layouts scroll the article inside a fixed-height pane. Our
    // progress tracking (and the phone's scrolling) expects document flow,
    // so remember the dominant vertical scroller and flatten it below.
    const overflowY = style.overflowY;
    if (
      (overflowY === "auto" || overflowY === "scroll") &&
      el.scrollHeight > el.clientHeight + 40 &&
      el.clientHeight >= window.innerHeight * 0.4 &&
      (!scroller || el.scrollHeight > scroller.scrollHeight)
    ) {
      scroller = el;
    }
  }
  for (const el of hidden) {
    if (el.isConnected) el.remove();
  }
  for (const el of fixed) {
    if (el.isConnected && !el.contains(scroller)) el.remove();
  }
  const flatten = (el) => {
    el.style.setProperty("height", "auto", "important");
    el.style.setProperty("max-height", "none", "important");
    el.style.setProperty("min-height", "0", "important");
    el.style.setProperty("overflow", "visible", "important");
  };
  if (scroller) {
    let node = scroller;
    while (node && node !== doc.documentElement) {
      flatten(node);
      node = node.parentElement;
    }
  }
  flatten(doc.documentElement);
  if (doc.body) flatten(doc.body);
  for (const el of doc.querySelectorAll("script, noscript, iframe, frame, object, embed, template, base")) {
    el.remove();
  }
  for (const el of doc.querySelectorAll("*")) {
    for (const attr of [...el.attributes]) {
      if (/^on/i.test(attr.name)) el.removeAttribute(attr.name);
    }
  }

  return {
    url: doc.location.href,
    html: "<!DOCTYPE html>\n" + doc.documentElement.outerHTML,
  };
}
