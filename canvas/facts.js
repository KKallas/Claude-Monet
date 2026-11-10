// What the server works out from a build and the Note's literals, in words for the panel: what a part is made of and
// what it weighs, what gravity asks of a joint, a named pose and what it keeps clear, the bill of materials. Plain
// functions of the report, no page: every line is text (the panel escapes it), with how it reads: ok, warn or err.

const round = (v, d = 1) => Math.round(v * 10 ** d) / 10 ** d;
const mm3 = (v) => `${round(v, v < 10 ? 2 : 1)} mm³`;

/** Grams as a person says them: 59.7 g, 4.1 kg. */
export const grams = (g) => (g == null ? 'no mass' : g >= 1000 ? `${round(g / 1000, 2)} kg` : `${round(g, g < 10 ? 2 : 1)} g`);

/** A material by its profile's own name (profiles/materials/<key>.json), else its key; none is bought. */
export const materialName = (key, profiles) => (key ? profiles?.[key]?.name ?? key : 'bought');

/** A material's numbers: 1.27 g/cm³ · to about 70 °C. */
export function materialWords(m, profiles) {
  if (!m) return '';
  const p = { ...(profiles?.[m.name] ?? {}), ...m };
  return [p.density != null ? `${p.density} g/cm³` : '', p.max_temp_c != null ? `to about ${p.max_temp_c} °C` : '',
    p.printed === false ? 'not printed' : ''].filter(Boolean).join(' · ');
}

/** Where a material was taken from (materials.of_parts' `how`), in words. */
export const howWords = (how) => (!how ? '' : how === 'project' ? "the project's" : how === 'MATERIAL' ? 'its MATERIAL' : how);

/** One part of an assembly as the report has it: a keep-out, bought, or a material and its grams. */
export function partWords(q, profiles) {
  if (!q) return '';
  if (q.keepout) return 'room kept clear, not material';
  return `${materialName(q.material, profiles)} · ${grams(q.mass_g)}`;
}

const driveName = (d) => d.servo ?? d.motor ?? d.name ?? d.model ?? 'the drive';

/** One line for a joint: the most gravity asks of it over its range, and where; the drive's margin over that.
 * `unit` is the joint's own (° or mm). Returns [text, level]. */
export function torqueWords(t, unit = '') {
  if (!t) return ['', ''];
  if (!(t.max > 1e-3)) return [`gravity: nothing to hold${t.without?.length ? ` (no mass for ${t.without.join(', ')})` : ''}`, ''];
  let s = `gravity: max ${round(t.max, 2)} ${t.unit} at ${round(t.at, 2)}${unit}`;
  if (t.at_driver) s += ` (${Object.entries(t.at_driver).map(([k, v]) => `${round(v, 2)} at ${k}`).join(', ')})`;
  let level = '';
  if (t.drive && t.margin != null) {
    s += `; ${driveName(t.drive)} margin ×${round(t.margin, t.margin < 10 ? 2 : 0)}`;
    level = t.margin < 1 ? 'err' : t.margin < 1.5 ? 'warn' : 'ok';
  }
  if (t.without?.length) s += `; without ${t.without.join(', ')} (no mass)`;
  return [s, level];
}

/** A named pose (report.motion.poses[name]): its lines, [text, level]. */
export function poseLines(p) {
  if (!p) return [];
  if (!p.resolved) return [[p.why || 'this pose cannot be taken', 'err']];
  const over = p.interference_mm3 > 0, hit = p.clash_mm3 > 0;
  const out = [[`${over ? `overlap ${mm3(p.interference_mm3)}` : 'nothing overlaps'} · `
    + `${hit ? `clash ${mm3(p.clash_mm3)}: ${(p.clashes ?? []).slice(0, 3).map(([a, b]) => `${a} × ${b}`).join(', ')}` : 'no clash'}`, hit ? 'err' : over ? 'warn' : 'ok']];
  for (const [k, v] of Object.entries(p.clear ?? {})) {
    const hits = (p.keepout_hits?.[k] ?? []).map(([part, vol]) => `${part} ${mm3(vol)}`);
    out.push(v > 1e-3 ? [`${k}: ${mm3(v)} in it${hits.length ? `, ${hits.join(', ')}` : ''}`, 'err'] : [`${k}: clear`, 'ok']);
  }
  return out;
}

/** What a pose sets, in short: the joints it moves off 0 (as built), with their units. */
export const poseValues = (values, joints) => Object.entries(values ?? {}).filter(([k, v]) => joints[k] && !joints[k].follows && joints[k].kind !== 'rigid' && Math.abs(v) > 1e-9)
  .map(([k, v]) => `${k} ${round(v, 2)}${joints[k].unit ?? ''}`).join(', ') || 'as built';

/** The bill of materials (GET …/bom), as lines in four lists: what to print, the cut list, what to buy, what the
 * BOM leaves out. Each line is [text, level]. */
export function bomLines(b, profiles) {
  const print = Object.entries(b?.printed ?? {}).map(([note, r]) => [[`${note} ×${r.qty}`, materialName(r.material, profiles), r.grams != null ? grams(r.grams) : '',
    r.pieces > 1 ? `in ${r.pieces} pieces` : '', r.fits_bed === false ? 'does not fit the bed' : ''].filter(Boolean).join(' · '), r.fits_bed === false ? 'err' : '']);
  const cut = Object.entries(b?.stock ?? {}).map(([name, r]) => [`${name}${r.material ? ` (${materialName(r.material, profiles)})` : ''}: `
    + `${r.cuts.map((c) => `${c.qty} × ${round(c.length_mm, 1)} mm`).join(', ')} · ${round(r.total_mm, 1)} mm in all`, '']);
  const buy = Object.entries(b?.bought ?? {}).map(([name, r]) => [`${name} ×${r.qty}${r.mass_g != null ? ` · ${grams(r.mass_g)}` : ''}`, '']);
  const unlisted = (b?.unlisted ?? []).length ? [[`not in the BOM: ${b.unlisted.join(', ')}`, 'warn']] : [];
  return { print, cut, buy, unlisted };
}
