// The words of canvas/facts.js, without a page: what the panel says of materials, torque, poses and the BOM.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { bomLines, grams, materialWords, partWords, poseLines, poseValues, torqueWords } from '../canvas/facts.js';

const PROFILES = { petg: { name: 'PETG', density: 1.27, max_temp_c: 70, printed: true }, aluminium: { name: 'Aluminium', density: 2.7, printed: false } };

test('grams as a person says them', () => {
  assert.equal(grams(59.741), '59.7 g');
  assert.equal(grams(4100.038), '4.1 kg');
  assert.equal(grams(null), 'no mass');
});

test('a part is a keep-out, bought, or a material and its mass', () => {
  assert.equal(partWords({ keepout: true }, PROFILES), 'room kept clear, not material');
  assert.equal(partWords({ material: null, mass_g: 2700 }, PROFILES), 'bought · 2.7 kg');
  assert.equal(partWords({ material: 'petg', mass_g: 59.741 }, PROFILES), 'PETG · 59.7 g');
  assert.equal(materialWords({ name: 'aluminium' }, PROFILES), '2.7 g/cm³ · not printed');
});

test('what gravity asks of a joint, and the drive that holds it', () => {
  const [text, level] = torqueWords({ unit: 'N·mm', max: 52.956, at: 0, drive: { servo: 'MG996R', torque_nmm: 900 }, margin: 16.995 }, '°');
  assert.equal(text, 'gravity: max 52.96 N·mm at 0°; MG996R margin ×17');
  assert.equal(level, 'ok');
  assert.equal(torqueWords({ unit: 'N·mm', max: 300, at: 45, drive: { servo: 'SG90' }, margin: 0.6 }, '°')[1], 'err');
  assert.equal(torqueWords({ unit: 'N·mm', max: 0, at: 0 })[0], 'gravity: nothing to hold');
  assert.deepEqual(torqueWords(undefined), ['', '']);
});

test('a named pose: what overlaps, what clashes, and every keep-out clear or not', () => {
  const ajar = { resolved: true, values: { leaf_left: 20, leaf_right: -20, arm: 0 }, interference_mm3: 0, clash_mm3: 0, clashes: [],
    clear: { keepout_beam: 11283.627 }, keepout_hits: { keepout_beam: [['leaf_left', 5641.813], ['leaf_right', 5641.813]] } };
  assert.deepEqual(poseLines(ajar), [['nothing overlaps · no clash', 'ok'], ['keepout_beam: 11283.6 mm³ in it, leaf_left 5641.8 mm³, leaf_right 5641.8 mm³', 'err']]);
  assert.deepEqual(poseLines({ ...ajar, clear: { keepout_beam: 0 } })[1], ['keepout_beam: clear', 'ok']);
  assert.deepEqual(poseLines({ resolved: false, why: 'leaf_left = 200 is outside its range [0, 90]' }), [['leaf_left = 200 is outside its range [0, 90]', 'err']]);
  const joints = { leaf_left: { kind: 'revolute', unit: '°' }, leaf_right: { kind: 'revolute', unit: '°' }, arm: { kind: 'revolute', unit: '°' } };
  assert.equal(poseValues(ajar.values, joints), 'leaf_left 20°, leaf_right -20°');
  assert.equal(poseValues({ arm: 0 }, joints), 'as built');
});

test('the BOM in four lists', () => {
  const L = bomLines({ printed: { leaf: { qty: 2, material: 'petg', grams: 119.5, pieces: 1, fits_bed: true }, big: { qty: 1, material: 'petg', grams: 900, pieces: 3, fits_bed: false } },
    stock: { tube: { cuts: [{ length_mm: 324, qty: 2 }, { length_mm: 92.5, qty: 4 }], count: 6, total_mm: 1018, material: 'aluminium' } },
    bought: { 'Epson EB-X49': { qty: 1, mass_g: null } }, unlisted: ['base'] }, PROFILES);
  assert.deepEqual(L.print, [['leaf ×2 · PETG · 119.5 g', ''], ['big ×1 · PETG · 900 g · in 3 pieces · does not fit the bed', 'err']]);
  assert.deepEqual(L.cut, [['tube (Aluminium): 2 × 324 mm, 4 × 92.5 mm · 1018 mm in all', '']]);
  assert.deepEqual(L.buy, [['Epson EB-X49 ×1', '']]);
  assert.deepEqual(L.unlisted, [['not in the BOM: base', 'warn']]);
});
