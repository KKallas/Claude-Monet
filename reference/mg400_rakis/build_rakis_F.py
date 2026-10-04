# build_rakis_F.py - MG400 table, version F (from E): everything stands on the table.
#
#  * Nest (robot plate) lies flat on the table, 24 mm tall, underside hollowed
#    with a rib grid under the robot. Split in two halves along y = 0.
#    Side rails along both sides carry the pipe tunnels; clamp ears at the
#    back corners, at table level.
#  * Gridfinity: lite (open-bottom) egg-crate lattice standing on the table,
#    with solid beams under the pipe lines.
#  * Pipes slide in from the side through SQUARE tunnels (print top-up: the
#    tunnel roof is a flat bridge, no supports):
#      - two long pipes (front-back) along the nest side rails and on through
#        the grid: they tie each nest half to its grid half
#      - one cross pipe inside the grid, joining the two grid halves
#
# Idempotent: rebuilds rakis_D; hides the other variants (not deleted).
import adsk.core, adsk.fusion, json, math, traceback

P = dict(
    clear=0.5, run=20.0, ramp_angle=20.0, rim=3.0,
    H=24.0,                 # total height, table to top surface
    pitch=42.0, cols=7, chunks=(4, 3), half_w=210.0, eps=0.01,
    pipe_d=16.0, tunnel=16.4, tunnel_floor=1.6, skin=1.2, rail_wall=3.0,
    nest_skin=3.0,          # robot floor skin over the ribs
    slot=10.0, rib=2.0, end_solid=20.0, mid_rib=4.0,   # nest underside ribs
    notch_w=24.0, notch_h=12.0,                        # cable arches in the lattice walls
    dowel=70.0, dowel_beam=80.0,                       # short cross pipes over the centre joint
    reach=400.0,
    bed=(256.0, 256.0),     # Bambu X1C
    # --- F ---
    table_depth=700.0,      # table edge to table edge along the pipes: SET THIS
    L_len=45.0, L_lip=5.0, L_drop=30.0, L_wall=4.0, socket=30.0,
    end_wall=2.0, end_floor=0.8, end_skin=1.2, end_rib=2.0,   # hollow end blocks
    ear_r=10.0, ear_h=0.4,  # snap-off anchor discs under the plate corners
)
OUTDIR = '/Users/kasparkallas/AI_tools/fusion_mg400/'
NAME = 'rakis_F_table'

VI = adsk.core.ValueInput
P3 = adsk.core.Point3D
FO = adsk.fusion.FeatureOperations
def cm(v): return v / 10.0
def mm(v): return round(v * 10.0, 2)

def body(comp, name):
    for b in comp.bRepBodies:
        if b.name == name:
            return b
    raise RuntimeError('no body ' + name)

def plane_at(comp, z):
    if abs(z) < 1e-9:
        return comp.xYConstructionPlane
    pi = comp.constructionPlanes.createInput()
    pi.setByOffset(comp.xYConstructionPlane, VI.createByReal(cm(z)))
    pl = comp.constructionPlanes.add(pi)
    pl.isLightBulbOn = False
    return pl

def rrect(sk, x0, y0, x1, y1, r):
    L, A = sk.sketchCurves.sketchLines, sk.sketchCurves.sketchArcs
    x0, y0, x1, y1, r = cm(x0), cm(y0), cm(x1), cm(y1), cm(r)
    h = math.pi / 2
    l1 = L.addByTwoPoints(P3.create(x0 + r, y0, 0), P3.create(x1 - r, y0, 0))
    a1 = A.addByCenterStartSweep(P3.create(x1 - r, y0 + r, 0), l1.endSketchPoint, h)
    l2 = L.addByTwoPoints(a1.endSketchPoint, P3.create(x1, y1 - r, 0))
    a2 = A.addByCenterStartSweep(P3.create(x1 - r, y1 - r, 0), l2.endSketchPoint, h)
    l3 = L.addByTwoPoints(a2.endSketchPoint, P3.create(x0 + r, y1, 0))
    a3 = A.addByCenterStartSweep(P3.create(x0 + r, y1 - r, 0), l3.endSketchPoint, h)
    l4 = L.addByTwoPoints(a3.endSketchPoint, P3.create(x0, y0 + r, 0))
    a4 = A.addByCenterStartSweep(P3.create(x0 + r, y0 + r, 0), l4.endSketchPoint, h)
    a4.endSketchPoint.merge(l1.startSketchPoint)

def rect(sk, x0, y0, x1, y1):
    sk.sketchCurves.sketchLines.addTwoPointRectangle(P3.create(cm(x0), cm(y0), 0), P3.create(cm(x1), cm(y1), 0))

def profs(sk):
    oc = adsk.core.ObjectCollection.create()
    for p in sk.profiles:
        oc.add(p)
    return oc

def extrude_z(comp, pr, z0, z1, op, parts=None):
    ex = comp.features.extrudeFeatures
    inp = ex.createInput(pr, op)
    inp.startExtent = adsk.fusion.OffsetStartDefinition.create(VI.createByReal(cm(z0)))
    inp.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(VI.createByReal(cm(z1 - z0))),
                         adsk.fusion.ExtentDirections.PositiveExtentDirection)
    if parts is not None:
        inp.participantBodies = parts
    return ex.add(inp)

def extrude_axis(comp, pr, plane, axis, a0, a1, op, parts=None):
    n = plane.geometry.normal
    s = n.y if axis == 'y' else n.x
    start = a0 if s > 0 else -a1
    ex = comp.features.extrudeFeatures
    inp = ex.createInput(pr, op)
    inp.startExtent = adsk.fusion.OffsetStartDefinition.create(VI.createByReal(cm(start)))
    inp.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(VI.createByReal(cm(a1 - a0))),
                         adsk.fusion.ExtentDirections.PositiveExtentDirection)
    if parts is not None:
        inp.participantBodies = parts
    return ex.add(inp)

def cut_down(comp, pr, depth, taper, parts):
    ex = comp.features.extrudeFeatures
    inp = ex.createInput(pr, FO.CutFeatureOperation)
    inp.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(VI.createByReal(cm(depth))),
                         adsk.fusion.ExtentDirections.NegativeExtentDirection,
                         VI.createByString('%.6f deg' % taper))
    inp.participantBodies = parts
    return ex.add(inp)

def vol(comp):
    return sum(b.volume for b in comp.bRepBodies)

def pick_taper_cut(comp, pr, depth, taper, names):
    res = []
    for s in (1, -1):
        v0 = vol(comp)
        try:
            f = cut_down(comp, pr, depth, s * taper, [body(comp, n) for n in names])
        except Exception:
            continue
        res.append((s, v0 - vol(comp)))
        f.deleteMe()
    s = min([r for r in res if r[1] > 0], key=lambda r: r[1])[0]
    cut_down(comp, pr, depth, s * taper, [body(comp, n) for n in names])
    return s

def box_along(comp, axis, c, a0, a1, z0, z1, op, parts, halfw):
    """Rectangle of half-width halfw around c (x for axis 'y', y for axis 'x'), z0..z1, swept along axis."""
    plane = comp.xZConstructionPlane if axis == 'y' else comp.yZConstructionPlane
    sk = comp.sketches.add(plane)
    if axis == 'y':
        q0, q1 = P3.create(cm(c - halfw), 0, cm(z0)), P3.create(cm(c + halfw), 0, cm(z1))
    else:
        q0, q1 = P3.create(0, cm(c - halfw), cm(z0)), P3.create(0, cm(c + halfw), cm(z1))
    sk.sketchCurves.sketchLines.addTwoPointRectangle(sk.modelToSketchSpace(q0), sk.modelToSketchSpace(q1))
    return extrude_axis(comp, profs(sk), plane, axis, a0, a1, op, parts)

def cyl_along(comp, axis, c, zc, a0, a1, r, name):
    plane = comp.xZConstructionPlane if axis == 'y' else comp.yZConstructionPlane
    sk = comp.sketches.add(plane)
    pc = P3.create(cm(c), 0, cm(zc)) if axis == 'y' else P3.create(0, cm(c), cm(zc))
    sk.sketchCurves.sketchCircles.addByCenterRadius(sk.modelToSketchSpace(pc), cm(r))
    f = extrude_axis(comp, profs(sk), plane, axis, a0, a1, FO.NewBodyFeatureOperation)
    f.bodies.item(0).name = name

# ===========================================================================
# Version E changes vs D:
#   * grid 7 columns deep (294 mm), split into x chunks of 4 + 3 columns
#   * long pipes run from the grid front to the nest back (~530 mm)
#   * pipe tunnels moved under the nest ramp so the nest is 243 mm wide and
#     can be split FRONT/BACK (x = 0); the two long pipes hold the halves
#   * nest = 2 mm full-profile slices / 10 mm gaps strung on the two pipes
#     (only the square tubes cross the gaps), 20 mm solid at each end,
#     4 mm slice on the split
#   * cable arches (24 x 12 mm) through every lattice wall at table level
#   * full-width cross pipes replaced by 70 mm dowels over the y = 0 joint
# ===========================================================================
def run():
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    for occ in list(root.occurrences):
        if occ.component.name == NAME:
            occ.deleteMe()
    for occ in root.occurrences:
        if occ.component.name.startswith('rakis_'):
            occ.isLightBulbOn = False

    base = [o for o in root.allOccurrences if o.fullPathName.endswith('2204132100_1:1')][0]
    bottom = None
    for f in base.bRepBodies.item(0).faces:
        g = f.geometry
        if g.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType and abs(g.normal.z) > 0.99 \
                and f.boundingBox.maxPoint.z < 0.001 and (bottom is None or f.area > bottom.area):
            bottom = f
    outer = [lp for lp in bottom.loops if lp.isOuter][0]

    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = NAME

    # ---------- levels ----------
    th = math.radians(P['ramp_angle'])
    depth = P['run'] * math.tan(th)
    z_top = depth
    T = z_top - P['H']
    z_pb = z_top - 4.65
    t0 = T + P['tunnel_floor']
    t1 = t0 + P['tunnel']
    beam_top = t1 + P['skin']
    assert beam_top <= z_pb + 1e-6, 'tunnel roof hits the bins: raise H'
    ht = P['tunnel'] / 2
    bw = ht + P['rail_wall']                      # beam / rail half width
    pocket_edge = 95 + P['clear']
    half_x = pocket_edge + P['run'] + P['rim']    # nest half length (x)
    # tunnel as far in as the ramp allows: ramp height over its inner edge = roof + skin
    y_in = pocket_edge + max(0.0, beam_top) / math.tan(th)
    y_long = y_in + ht
    half_y = max(y_in + P['tunnel'] + P['rail_wall'], half_x)
    x_seam = -half_x
    pt = P['pitch']
    x_front = x_seam - pt * P['cols']
    rep = {'params': P, 'levels': {'table': round(T, 2), 'robot_floor': 0, 'top': round(z_top, 2),
                                   'tunnel_z': [round(t0, 2), round(t1, 2)], 'tunnel_y': round(y_long, 2)}}

    # ---------- nest ----------
    sk = comp.sketches.add(comp.xYConstructionPlane)
    rrect(sk, -half_x, -half_y, half_x, half_y, 6)
    extrude_z(comp, profs(sk), T, z_top, FO.NewBodyFeatureOperation).bodies.item(0).name = 'nest'
    sk = comp.sketches.add(plane_at(comp, z_top))
    pj = adsk.core.ObjectCollection.create()
    for e in outer.edges:
        for ent in sk.project(e):
            pj.add(ent)
    sk.offset(pj, P3.create(100, 100, 0), cm(P['clear'] + P['run']))
    sign = pick_taper_cut(comp, profs(sk), depth, 90.0 - P['ramp_angle'], ['nest'])
    # sliced plate: 2 mm full-profile slices every 12 mm, strung on the pipes.
    # In each 10 mm gap only the square tube around each pipe remains.
    y_tube_in = y_in - P['rail_wall']              # inner face of the tube around the pipe
    sk_mid = comp.sketches.add(comp.xYConstructionPlane)   # between the tubes: full height
    sk_top = comp.sketches.add(comp.xYConstructionPlane)   # over the tubes: above the tube roof
    c = P['mid_rib'] / 2 + P['slot'] / 2
    slots = 0
    while c + P['slot'] / 2 <= half_x - P['end_solid'] + 1e-6:
        for s in (1, -1):
            xa, xb = s * c - P['slot'] / 2, s * c + P['slot'] / 2
            rect(sk_mid, xa, -y_tube_in, xb, y_tube_in)
            rect(sk_top, xa, y_tube_in, xb, half_y + 1)
            rect(sk_top, xa, -half_y - 1, xb, -y_tube_in)
            slots += 1
        c += P['slot'] + P['rib']
    extrude_z(comp, profs(sk_mid), T - 1, z_top + 1, FO.CutFeatureOperation, [body(comp, 'nest')])
    extrude_z(comp, profs(sk_top), beam_top, z_top + 1, FO.CutFeatureOperation, [body(comp, 'nest')])
    rep['nest_gaps'] = slots
    si = comp.features.splitBodyFeatures.createInput(body(comp, 'nest'), comp.yZConstructionPlane, True)
    comp.features.splitBodyFeatures.add(si)
    for b in [b for b in comp.bRepBodies if b.name.startswith('nest')]:
        b.name = 'nest_back' if (b.boundingBox.minPoint.x + b.boundingBox.maxPoint.x) > 0 else 'nest_front'
    # hollow the solid end blocks: closed box (0.8 mm floor on the bed), 2 mm walls,
    # 2 mm ribs across, roof 1.2 mm under the lowest point of the ramp above it
    x0e = half_x - P['end_solid'] + P['end_wall']
    x1e = half_x - P['end_wall']
    z_cav_top = (x0e - pocket_edge) * math.tan(th) - P['end_skin']
    y_cav = y_in - P['rail_wall'] - P['end_wall']
    segs_y = [(-y_cav, -49.0), (-47.0, -1.0), (1.0, 47.0), (49.0, y_cav)]
    for nm, s_ in (('nest_back', 1), ('nest_front', -1)):
        sk = comp.sketches.add(comp.xYConstructionPlane)
        xa, xb = sorted((s_ * x0e, s_ * x1e))
        for (ya, yb) in segs_y:
            rect(sk, xa, ya, xb, yb)
        extrude_z(comp, profs(sk), T + P['end_floor'], z_cav_top, FO.CutFeatureOperation, [body(comp, nm)])
    rep['end_cavity_z'] = [round(T + P['end_floor'], 2), round(z_cav_top, 2)]
    # snap-off anchor discs (mouse ears) under every corner of both plate halves
    for nm, s_ in (('nest_back', 1), ('nest_front', -1)):
        sk = comp.sketches.add(comp.xYConstructionPlane)
        for xc in (s_ * half_x, s_ * (P['ear_r'] + 1.0)):
            for yc in (half_y - 5.0, -(half_y - 5.0)):   # inset so the plate stays inside 256 mm
                sk.sketchCurves.sketchCircles.addByCenterRadius(P3.create(cm(xc), cm(yc), 0), cm(P['ear_r']))
        extrude_z(comp, profs(sk), T, T + P['ear_h'], FO.JoinFeatureOperation, [body(comp, nm)])

    # ---------- grid ----------
    kmax = int(P['half_w'] // pt)
    cells = [(x_seam - pt / 2 - pt * i, pt / 2 + pt * k, i) for i in range(P['cols']) for k in range(-kmax, kmax)]
    bounds, c0 = [], 0
    for n in P['chunks']:
        bounds.append((x_seam - pt * (c0 + n), x_seam - pt * c0))
        c0 += n
    tiles = []
    for j, (xa, xb) in enumerate(bounds):
        for s, side in ((1, 'pos'), (-1, 'neg')):
            sk = comp.sketches.add(comp.xYConstructionPlane)
            y0, y1 = sorted((0.0, s * P['half_w']))
            rect(sk, xa, y0, xb, y1)
            nm = 'grid_%s_%d' % (side, j)
            extrude_z(comp, profs(sk), T, z_top, FO.NewBodyFeatureOperation).bodies.item(0).name = nm
            tiles.append(nm)
    e = P['eps']
    steps = [(z_top, 2.15, 45.0, pt / 2 - e, 4.0 - e),
             (z_top - 2.15, 1.8, 0.0, pt / 2 - e - 2.15, 1.85 - e),
             (z_top - 3.95, 0.7, 45.0, pt / 2 - e - 2.15, 1.85 - e),
             (z_pb, z_pb - T + 1, 0.0, pt / 2 - e - 2.85, 1.15 - e)]
    for (zs, d, tap, hh, r) in steps:
        sk = comp.sketches.add(plane_at(comp, zs))
        sk.isComputeDeferred = True
        for (cx, cy, _) in cells:
            rrect(sk, cx - hh, cy - hh, cx + hh, cy + hh, r)
        sk.isComputeDeferred = False
        cut_down(comp, profs(sk), d, sign * tap, [body(comp, n) for n in tiles])
    # cable arches through every wall segment (beams added later fill them back where needed)
    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.isComputeDeferred = True
    seen = set()
    nw, tw = P['notch_w'] / 2, 4.0
    for (cx, cy, _) in cells:
        for (mx, my, along_y) in ((cx - pt / 2, cy, True), (cx + pt / 2, cy, True),
                                  (cx, cy - pt / 2, False), (cx, cy + pt / 2, False)):
            key = (round(mx, 2), round(my, 2))
            if key in seen:
                continue
            seen.add(key)
            if along_y:
                rect(sk, mx - tw, my - nw, mx + tw, my + nw)
            else:
                rect(sk, mx - nw, my - tw, mx + nw, my + tw)
    sk.isComputeDeferred = False
    extrude_z(comp, profs(sk), T - 1, T + P['notch_h'], FO.CutFeatureOperation, [body(comp, n) for n in tiles])
    rep['cable_arches'] = len(seen)
    # beams: long ones under the pipe lines, short dowel beams across y = 0
    dowel_x = []
    for j, (xa, xb) in enumerate(bounds):
        xc = (xa + xb) / 2
        dowel_x.append(xc)
        for s, side in ((1, 'pos'), (-1, 'neg')):
            nm = 'grid_%s_%d' % (side, j)
            box_along(comp, 'x', s * y_long, xa, xb, T, beam_top, FO.JoinFeatureOperation, [body(comp, nm)], bw)
            a0, a1 = sorted((0.0, s * P['dowel_beam'] / 2))
            box_along(comp, 'y', xc, a0, a1, T, beam_top, FO.JoinFeatureOperation, [body(comp, nm)], bw)

    # ---------- square tunnels ----------
    mods = [b for b in comp.bRepBodies]
    for s in (1, -1):
        box_along(comp, 'x', s * y_long, x_front - 1, half_x + 1, t0, t1, FO.CutFeatureOperation, mods, ht)
    dt = P['dowel'] / 2 + 2.0
    for xc in dowel_x:
        box_along(comp, 'y', xc, -dt, dt, t0, t1, FO.CutFeatureOperation, mods, ht)

    # ---------- pipes ----------
    zc = t0 + P['pipe_d'] / 2
    # table edges: back L sits against the plate back, front L at the other table edge
    x_edge_b = half_x + P['L_len']
    x_edge_f = x_edge_b - P['table_depth']
    x_in_f = x_edge_f + P['L_len']
    need = round(x_edge_b - (x_front - P['L_len']), 1)
    assert x_in_f <= x_front + 1e-6, 'table_depth too small: needs at least %.0f mm' % need
    p0 = x_edge_f + (P['L_len'] - P['socket'])
    p1 = x_edge_b - (P['L_len'] - P['socket'])
    long_len = round(p1 - p0, 1)
    for s in (1, -1):
        cyl_along(comp, 'x', s * y_long, zc, p0, p1, P['pipe_d'] / 2,
                  'pipe_long_%s' % ('pos' if s > 0 else 'neg'))
    # the L's: foot on the table holding the pipe end, lip hooking down over the table edge
    L_top = t1 + P['L_wall']
    L_hw = ht + P['L_wall']
    Ls = []
    for (edge, d, tag) in ((x_edge_b, 1, 'back'), (x_edge_f, -1, 'front')):
        for s in (1, -1):
            nm = 'L_%s_%s' % (tag, 'pos' if s > 0 else 'neg')
            foot = sorted((edge - d * P['L_len'], edge))
            f = box_along(comp, 'x', s * y_long, foot[0], foot[1], T, L_top, FO.NewBodyFeatureOperation, None, L_hw)
            f.bodies.item(0).name = nm
            lip = sorted((edge, edge + d * P['L_lip']))
            box_along(comp, 'x', s * y_long, lip[0], lip[1], T - P['L_drop'], L_top,
                      FO.JoinFeatureOperation, [body(comp, nm)], L_hw)
            sock = sorted((edge - d * (P['L_len'] + 1), edge - d * (P['L_len'] - P['socket'])))
            box_along(comp, 'x', s * y_long, sock[0], sock[1], t0, t1, FO.CutFeatureOperation, [body(comp, nm)], ht)
            Ls.append(nm)
    rep['table'] = {'depth': P['table_depth'], 'min_depth': need,
                    'front_edge_x': round(x_edge_f, 1), 'back_edge_x': round(x_edge_b, 1),
                    'free_pipe_in_front_of_grid': round(x_front - x_in_f, 1)}
    for j, xc in enumerate(dowel_x):
        cyl_along(comp, 'y', xc, zc, -P['dowel'] / 2, P['dowel'] / 2, P['pipe_d'] / 2, 'pipe_dowel_%d' % j)
    for s in comp.sketches:
        s.isVisible = False

    rep['pipes'] = {'long_mm': [long_len, long_len], 'dowels_mm': [P['dowel']] * len(dowel_x), 'Ls': Ls}
    far = sorted({round(math.hypot(cx, cy)) for (cx, cy, _) in cells if math.hypot(cx, cy) > P['reach']})
    rep['cells'] = len(cells)
    rep['cells_beyond_reach'] = {'limit': P['reach'], 'count': sum(1 for (cx, cy, _) in cells
                                                                 if math.hypot(cx, cy) > P['reach']),
                                 'radii': far}
    rep['bodies'] = []
    for b in comp.bRepBodies:
        bx = b.boundingBox
        sx, sy = mm(bx.maxPoint.x - bx.minPoint.x), mm(bx.maxPoint.y - bx.minPoint.y)
        rep['bodies'].append({'name': b.name, 'size_xy': [sx, sy],
                              'z': [mm(bx.minPoint.z), mm(bx.maxPoint.z)],
                              'volume_cm3': round(b.volume, 1),
                              'fits_bed': b.name.startswith('pipe') or
                              (min(sx, sy) <= min(P['bed']) and max(sx, sy) <= max(P['bed']))})
    with open(OUTDIR + 'F_report.json', 'w') as fh:
        json.dump(rep, fh, indent=1)
    print('rakis_F built ->', OUTDIR + 'F_report.json')

try:
    run()
except Exception:
    with open(OUTDIR + 'F_report.json', 'w') as fh:
        fh.write('ERROR\n' + traceback.format_exc())
    print(traceback.format_exc())
