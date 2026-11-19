// Markdown as the Docs room reads it (PROJECT.md, the project's docs, Monet's own). The text is escaped first, and no
// tag comes from it: every tag here is made by one of these patterns. Links go to https:// addresses (a new tab), or
// to another doc of the project (data-doc: the room opens it); images only from https://.

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** A link's target as the room may follow it: an https address, or a relative path to a .md (resolved against the
 *  doc it is in), or nothing. */
export function target(href, from = '') {
  const h = String(href ?? '').trim();
  if (/^https:\/\/[^\s"'<>]+$/.test(h)) return { href: h };
  const m = /^([A-Za-z0-9_./-]+\.md)(#[\w-]*)?$/.exec(h);
  if (!m || m[1].startsWith('/')) return null;
  const parts = from.split('/').slice(0, -1);
  for (const p of m[1].split('/')) {
    if (p === '..') { if (!parts.length) return null; parts.pop(); } else if (p && p !== '.') parts.push(p);
  }
  return { doc: parts.join('/') };
}

/** Within a line: `code`, **bold**, *italic*, ~~struck~~, [words](target), ![words](https://…) and bare addresses. */
export function inline(text, from = '') {
  const codes = [];
  let s = esc(text).replace(/`([^`]+)`/g, (_m, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = s.replace(/!\[([^\]]*)\]\((https:\/\/[^\s)]+)\)/g, (_m, alt, src) => `<img alt="${alt}" src="${src}" loading="lazy">`)
    .replace(/\[([^\]]+)\]\(([^\s)]+)\)/g, (m, words, href) => {
      const t = target(href.replace(/&amp;/g, '&'), from);
      if (!t) return m;
      return t.doc != null ? `<a href="#" data-doc="${esc(t.doc)}">${words}</a>` : `<a href="${esc(t.href)}" target="_blank" rel="noopener noreferrer">${words}</a>`;
    })
    .replace(/(^|[\s(])(https:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\w)/g, '$1<i>$2</i>')
    .replace(/(^|[^_\w])_([^_\s][^_]*?)_(?!\w)/g, '$1<i>$2</i>')
    .replace(/~~([^~]+)~~/g, '<s>$1</s>');
  return s.replace(/\u0000(\d+)\u0000/g, (_m, i) => `<code>${codes[i]}</code>`);
}

const cells = (line) => line.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());

/** Headings, lists (with boxes to tick), quotes, rules, tables, fenced code, paragraphs. `from`: the doc's own path,
 *  for its relative links. */
export function markdown(text, from = '') {
  const out = [];
  const lines = String(text ?? '').replace(/\r\n/g, '\n').split('\n');
  let list = '', para = [], code = null, quote = [];
  const endPara = () => { if (para.length) { out.push(`<p>${para.map((l) => inline(l, from)).join('<br>')}</p>`); para = []; } };
  const endList = () => { if (list) { out.push(`</${list}>`); list = ''; } };
  const endQuote = () => { if (quote.length) { out.push(`<blockquote>${markdown(quote.join('\n'), from)}</blockquote>`); quote = []; } };
  const endAll = () => { endPara(); endList(); endQuote(); };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (code) {
      if (/^```/.test(line)) { out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`); code = null; } else code.push(line);
      continue;
    }
    if (/^```/.test(line)) { endAll(); code = []; continue; }
    const q = /^>\s?(.*)$/.exec(line);
    if (q) { endPara(); endList(); quote.push(q[1]); continue; }
    endQuote();
    const h = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line), li = /^\s*(?:([-*+])|(\d+)[.)])\s+(.*)$/.exec(line);
    if (h) { endPara(); endList(); out.push(`<h${h[1].length}>${inline(h[2], from)}</h${h[1].length}>`); continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { endPara(); endList(); out.push('<hr>'); continue; }
    // a table: a row of cells, then a row of dashes under it
    if (/\|/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1])) {
      endPara(); endList();
      const head = cells(line), align = cells(lines[i + 1]).map((c) => (/^:-+:$/.test(c) ? 'center' : /-:$/.test(c) ? 'right' : ''));
      const td = (tag, c, k) => `<${tag}${align[k] ? ` style="text-align:${align[k]}"` : ''}>${inline(c, from)}</${tag}>`;
      const rows = [`<tr>${head.map((c, k) => td('th', c, k)).join('')}</tr>`];
      for (i += 2; i < lines.length && /\|/.test(lines[i]) && lines[i].trim(); i++) rows.push(`<tr>${cells(lines[i]).map((c, k) => td('td', c, k)).join('')}</tr>`);
      i--;
      out.push(`<table>${rows.join('')}</table>`);
      continue;
    }
    if (li) {
      endPara();
      const kind = li[1] ? 'ul' : 'ol';
      if (list !== kind) { endList(); out.push(`<${kind}>`); list = kind; }
      const box = /^\[( |x|X)\]\s+(.*)$/.exec(li[3]);
      out.push(box ? `<li class="${box[1] === ' ' ? 'todo' : 'done'}">${inline(box[2], from)}</li>` : `<li>${inline(li[3], from)}</li>`);
      continue;
    }
    if (!line.trim()) { endAll(); continue; }
    if (list && /^\s+\S/.test(line)) { out[out.length - 1] = out[out.length - 1].replace(/<\/li>$/, ` ${inline(line.trim(), from)}</li>`); continue; }
    endList();
    para.push(line);
  }
  if (code) out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
  endAll();
  return out.join('\n');
}
