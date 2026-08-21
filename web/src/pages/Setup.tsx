import { Link } from "react-router-dom";

function bookmarkletHref(origin: string): string {
  const source = `(function(){fetch('${origin}/api/articles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:location.href,title:document.title})}).then(function(r){if(!r.ok){throw new Error(String(r.status))}return r.json()}).then(function(d){var t=document.createElement('div');t.textContent=d.duplicate?'nano::nerd: already saved':'nano::nerd: saved';t.style.cssText='position:fixed;top:16px;right:16px;z-index:2147483647;background:#111;color:#fff;padding:10px 14px;border-radius:8px;font:14px system-ui';document.body.appendChild(t);setTimeout(function(){t.remove()},2000)}).catch(function(){alert('nano::nerd: save failed')})})();`;
  return `javascript:${encodeURIComponent(source)}`;
}

export default function Setup() {
  const origin = window.location.origin;
  // React refuses javascript: URLs on <a href>, which is exactly what a
  // bookmarklet is — inject the anchor as raw HTML on purpose.
  const anchorHtml = `<a class="bookmarklet" href="${bookmarkletHref(origin)}">Save to nano::nerd</a>`;
  const apiUrl = `${origin}/api/articles`;

  return (
    <>
      <nav className="top-nav">
        <Link className="brand" to="/library">nano::nerd</Link>
        <Link to="/library">library</Link>
      </nav>
      <main className="setup">
        <h2>Browser extension (Chrome / Arc — recommended)</h2>
        <p>
          The extension saves from a background worker, so it works even on
          sites whose Content Security Policy blocks the bookmarklet. One-time
          install:
        </p>
        <ol>
          <li>Open <code>chrome://extensions</code> (Arc: same address) and enable <strong>Developer mode</strong> (top right).</li>
          <li>Click <strong>Load unpacked</strong> and pick the <code>extension/</code> folder in the nanonerd repo.</li>
          <li>Pin the icon, then click it on any page to save — or press <strong>⌘⇧S</strong>, or right-click a link → <strong>Save link to nano::nerd</strong>.</li>
          <li>If your reader isn't at <code>http://localhost:8000</code>, set the API URL in the extension's Options.</li>
        </ol>

        <h2>Bookmarklet (fallback)</h2>
        <p>
          Drag this button to your bookmarks bar. Click it on any article to
          save it here.
        </p>
        <div dangerouslySetInnerHTML={{ __html: anchorHtml }} />
        <p>
          Some sites block cross-origin requests with a strict Content
          Security Policy; if the toast never appears, use the extension or
          the API directly (see below).
        </p>

        <h2>iPhone share sheet</h2>
        <p>One-time setup in the Shortcuts app (~2 minutes):</p>
        <ol>
          <li>Open <strong>Shortcuts</strong>, tap <strong>+</strong> to create a new shortcut.</li>
          <li>Tap the shortcut's settings (ⓘ) and enable <strong>Show in Share Sheet</strong>. Set the accepted types to <strong>URLs</strong>.</li>
          <li>Add the action <strong>Get Contents of URL</strong>.</li>
          <li>Expand it: set URL to <code>{apiUrl}</code>, Method <strong>POST</strong>, Request Body <strong>JSON</strong>, and add a field <code>url</code> = <strong>Shortcut Input</strong>.</li>
          <li>(Optional) Add <strong>Show Notification</strong> with the result.</li>
          <li>Rename the shortcut <strong>Save to nano::nerd</strong>.</li>
        </ol>
        <p>
          Then in Safari (or any app), tap Share → <strong>Save to
          nano::nerd</strong>.
        </p>

        <h2>API</h2>
        <p>
          <code>{`curl -X POST ${apiUrl} -H 'Content-Type: application/json' -d '{"url": "https://…"}'`}</code>
        </p>
      </main>
    </>
  );
}
