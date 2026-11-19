// The Docs room's editor: CodeMirror 6, from the CDN by the import map (index.html), loaded only when the room is first
// opened. One pane: Markdown is drawn as it is written (headings large, bold bold, code in the mono face) with its marks
// left in, dimmed, so what is typed is what is saved; Python is coloured. Nothing of ours is drawn by hand here.
import { EditorView, keymap, lineNumbers, drawSelection, highlightActiveLine, highlightActiveLineGutter, placeholder } from '@codemirror/view';
import { EditorState } from '@codemirror/state';
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
import { syntaxHighlighting, HighlightStyle, indentOnInput, bracketMatching } from '@codemirror/language';
import { markdown, markdownLanguage } from '@codemirror/lang-markdown';
import { python } from '@codemirror/lang-python';
import { tags as t } from '@lezer/highlight';

const MONO = "'Share Tech Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

// Markdown as it is written: the marks (#, **, `, list bullets) are processingInstruction, dimmed
const prose = HighlightStyle.define([
  { tag: t.heading1, fontSize: '1.7em', fontWeight: '700', color: 'var(--text-bright)' },
  { tag: t.heading2, fontSize: '1.4em', fontWeight: '700', color: 'var(--text-bright)' },
  { tag: t.heading3, fontSize: '1.2em', fontWeight: '700', color: 'var(--text-bright)' },
  { tag: [t.heading4, t.heading5, t.heading6], fontSize: '1.05em', fontWeight: '700', color: 'var(--text-bright)' },
  { tag: t.strong, fontWeight: '700', color: 'var(--text-bright)' },
  { tag: t.emphasis, fontStyle: 'italic' },
  { tag: t.strikethrough, textDecoration: 'line-through' },
  { tag: [t.link, t.url], color: 'var(--accent)' },
  { tag: t.monospace, fontFamily: MONO, color: 'var(--yellow, #ffd23f)' },
  { tag: t.quote, fontStyle: 'italic', color: 'var(--text-muted)' },
  { tag: [t.processingInstruction, t.contentSeparator, t.labelName], color: 'var(--text-muted)', opacity: '0.7' },
  { tag: t.atom, color: 'var(--accent)' },
]);
// Python, in the skin's colours
const code = HighlightStyle.define([
  { tag: [t.keyword, t.controlKeyword, t.definitionKeyword, t.moduleKeyword, t.operatorKeyword], color: 'var(--accent)' },
  { tag: [t.string, t.special(t.string)], color: '#9cc7a4' },
  { tag: [t.number, t.bool, t.null], color: 'var(--yellow, #ffd23f)' },
  { tag: [t.comment, t.lineComment, t.blockComment], color: 'var(--text-muted)', fontStyle: 'italic' },
  { tag: [t.function(t.definition(t.variableName)), t.definition(t.className)], color: 'var(--text-bright)', fontWeight: '700' },
  { tag: [t.className, t.typeName], color: '#c9a3d0' },
  { tag: t.docString, color: '#b8cf94' },
]);

const skin = EditorView.theme({
  '&': { height: '100%', color: 'var(--text)', backgroundColor: 'transparent', fontSize: '14px' },
  '.cm-scroller': { fontFamily: 'inherit', lineHeight: '1.6', overflow: 'auto' },
  '.cm-content': { caretColor: 'var(--accent)', padding: '14px 0 40vh' },
  '.cm-line': { padding: '0 22px' },
  '&.cm-focused': { outline: 'none' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--accent)', borderLeftWidth: '2px' },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection': { backgroundColor: 'rgba(94, 246, 255, .22) !important' },
  '.cm-activeLine': { backgroundColor: 'rgba(94, 246, 255, .045)' },
  '.cm-gutters': { backgroundColor: 'transparent', color: 'var(--text-muted)', border: 'none', fontFamily: MONO },
  '.cm-activeLineGutter': { backgroundColor: 'transparent', color: 'var(--accent)' },
  '.cm-matchingBracket': { outline: '1px solid var(--border-strong)', backgroundColor: 'transparent' },
  '.cm-placeholder': { color: 'var(--text-muted)' },
}, { dark: true });

/** An editor in `parent`. hooks: { changed(text), save() }. set(text, kind: 'md'|'py', readonly) puts a file in it,
 *  with a history of its own (undo does not go back into the file before). */
export function makeEditor(parent, hooks) {
  const modeOf = (k) => (k === 'py'
    ? [python(), syntaxHighlighting(code), lineNumbers(), highlightActiveLineGutter(), EditorView.contentAttributes.of({ style: `font-family:${MONO};font-size:13px` })]
    : [markdown({ base: markdownLanguage }), syntaxHighlighting(prose), EditorView.lineWrapping]);
  const stateOf = (doc, k, readonly) => EditorState.create({
    doc,
    extensions: [
      history(), drawSelection(), highlightActiveLine(), indentOnInput(), bracketMatching(),
      keymap.of([{ key: 'Mod-s', preventDefault: true, run: () => { hooks.save?.(); return true; } }, indentWithTab, ...defaultKeymap, ...historyKeymap]),
      placeholder(readonly ? '' : 'Empty. Write here: # a heading, **bold**, - a list, - [ ] a box to tick…'),
      skin, modeOf(k), EditorState.readOnly.of(readonly), EditorView.editable.of(!readonly),
      EditorView.updateListener.of((u) => { if (u.docChanged) hooks.changed?.(u.state.doc.toString()); }),
    ],
  });
  const view = new EditorView({ parent, state: stateOf('', 'md', true) });
  return {
    view,
    get text() { return view.state.doc.toString(); },
    set(text, k = 'md', readonly = false) { view.setState(stateOf(text, k, readonly)); view.scrollDOM.scrollTop = 0; },
    focus() { view.focus(); },
  };
}
