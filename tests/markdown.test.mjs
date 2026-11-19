// The Docs room's Markdown: what it makes, and that no tag comes from the text itself.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { markdown, target } from '../canvas/markdown.js';

test('the text is escaped first: no tag of its own gets through', () => {
  const html = markdown('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n**<b>x</b>**\n\n`<i>`');
  assert.ok(!/<script|<img src=x|onerror=alert\(1\)>/.test(html), html);
  assert.ok(html.includes('&lt;script&gt;') && html.includes('<code>&lt;i&gt;</code>'));
});

test('links go to https or to another doc; anything else stays words', () => {
  const html = markdown('[a](https://example.com/x) [b](javascript:alert(1)) [c](wiring.md) [d](../up.md) [e](http://plain.com) ![p](https://e.com/p.png) ![q](javascript:x)', 'docs/x.md');
  assert.ok(html.includes('<a href="https://example.com/x" target="_blank" rel="noopener noreferrer">a</a>'));
  assert.ok(!html.includes('href="javascript'));
  assert.ok(html.includes('data-doc="docs/wiring.md"') && html.includes('data-doc="up.md"'));
  assert.ok(!html.includes('href="http://plain.com"'));
  assert.ok(html.includes('<img alt="p" src="https://e.com/p.png"') && !html.includes('src="javascript'));
  assert.equal(target('../../x.md', 'a.md'), null);      // not out of the project
  assert.equal(target('/etc/x.md'), null);
});

test('headings, lists with boxes, quotes, rules, tables and code', () => {
  const html = markdown('# One\n###### Six\n\n- [ ] todo\n- [x] done\n1. first\n\n> said\n\n---\n\n| a | b |\n|---|--:|\n| 1 | *2* |\n\n```\n<x>\n```');
  for (const want of ['<h1>One</h1>', '<h6>Six</h6>', '<li class="todo">todo</li>', '<li class="done">done</li>', '<ol>', '<blockquote><p>said</p></blockquote>',
    '<hr>', '<th>a</th>', '<td style="text-align:right"><i>2</i></td>', '<pre><code>&lt;x&gt;</code></pre>']) assert.ok(html.includes(want), `${want} in ${html}`);
});

test('a note becomes a new-issue address of the repository, short enough for GitHub', async () => {
  const { issueUrl } = await import('../canvas/share.js');
  const long = 'x'.repeat(20000);
  const url = issueUrl('owner/repo', { title: 'Hex bolts & <b>', text: long, study: 'tool lock', project: 'arm', note: 'arm', frame: 60, fps: 30, length: 120, link: 'https://m.example/s/T#f=60' });
  assert.ok(url.startsWith('https://github.com/owner/repo/issues/new?') && url.length <= 7800, url.length);
  const q = new URL(url).searchParams;
  assert.equal(q.get('title'), 'Hex bolts & <b>');
  assert.ok(q.get('body').includes('frame 60 of 120 (2.0 s)') && q.get('body').includes('[Open this moment in Monet](https://m.example/s/T#f=60)'));
});
