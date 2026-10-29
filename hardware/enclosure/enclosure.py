"""Build and verify the current three-part enclosure in millimetres."""

import json
from pathlib import Path

import cadquery as cq
import trimesh
import base_geometry as base

ROOT = Path(__file__).resolve().parent
box = base.box

parts, references = base.build(include_speaker_bridge=False)
parts.pop('speaker_bridge')
references.pop('speaker_pad')
# Remove the crossbar above the insertion opening. Keep both side rails.
body = parts['body'].cut(box(2, -1, 58.19, 56, 3, 3)).clean()
carrier = parts['carrier']
for x, y in base.amplifier_holes():
    carrier = carrier.cut(base.cylinder(x, y, base.CARRIER_TOP, 3, 12))
references.pop('electronics_spacers')
references.pop('electronics_fasteners')

# Grip the brown perfboard. Keep 10 mm below the lower lips for its rear wires.
# Raising the assembly 0.8 mm preserves the original 1.6 mm lower lip thickness.
PERFBOARD_RISE = 0.8
for name in ('electronics_envelope', 'electronics_plug_space'):
    references[name] = references[name].translate((0, 0, PERFBOARD_RISE))
RAIL_Y, RAIL_LENGTH = 85.3, 15.0
CHANNEL_BOTTOM = base.ELECTRONICS_PCB_Z + PERFBOARD_RISE - 0.2
CHANNEL_TOP = CHANNEL_BOTTOM + 2.2
UPPER_LIP = 1.4
for outer, inner in ((2.3, 3.7), (24.3, 25.7)):
    upright = box(outer, RAIL_Y, base.CARRIER_TOP, inner - outer,
                  RAIL_LENGTH + 1.6, CHANNEL_TOP + UPPER_LIP - base.CARRIER_TOP)
    lip_x = 2.3 if outer < 10 else 23.0
    lower = box(lip_x, RAIL_Y, CHANNEL_BOTTOM - 1.6, 2.7, RAIL_LENGTH, 1.6)
    upper = box(lip_x, RAIL_Y, CHANNEL_TOP, 2.7, RAIL_LENGTH, UPPER_LIP)
    stop = box(lip_x, RAIL_Y + RAIL_LENGTH, CHANNEL_BOTTOM - 1.6,
               2.7, 1.6, CHANNEL_TOP - CHANNEL_BOTTOM + 1.6 + UPPER_LIP)
    carrier = carrier.union(upright).union(lower).union(upper).union(stop)
# Join the far ends with a third grooved rail, leaving the entry end open.
end_y = RAIL_Y + RAIL_LENGTH
end_wall = box(2.3, end_y, CHANNEL_BOTTOM - 1.6, 23.4, 1.6,
               CHANNEL_TOP - CHANNEL_BOTTOM + 1.6 + UPPER_LIP)
end_lower = box(2.3, end_y - 1, CHANNEL_BOTTOM - 1.6, 23.4, 1, 1.6)
end_upper = box(2.3, end_y - 1, CHANNEL_TOP, 23.4, 1, UPPER_LIP)
carrier = carrier.union(end_wall).union(end_lower).union(end_upper)
parts['carrier'] = carrier.clean()

# Each tongue is rooted toward the far end and free at the insertion end.
lid = box(2.3, 0.3, base.LID_BOTTOM, 55.4, 147.4, 2)
for mirrored in (False, True):
    slot = box(5.3, -0.5, 55, 1.8, 36.5, 4)
    slot = slot.union(base.cylinder(6.2, 36, 55, 0.9, 4))
    nose = (cq.Workplane('XY')
            .polyline([(2.4, 7), (0.6, 7), (0.6, 10), (2.4, 14)])
            .close().extrude(2.2).translate((0, 0, base.LID_BOTTOM - 0.1)))
    window = box(-1, 6.5, 55.6, 3.2, 8, 2.6)
    if mirrored:
        slot = slot.mirror('YZ', (30, 0, 0))
        nose = nose.mirror('YZ', (30, 0, 0))
        window = window.mirror('YZ', (30, 0, 0))
    lid = lid.cut(slot).union(nose)
    body = body.cut(window)

# Preserve the existing wall-mount opening.
keyhole = base.cylinder(30, 130, 54.9, 4.5, 5)
keyhole = keyhole.union(box(27.75, 130, 54.9, 4.5, 10, 5))
keyhole = keyhole.union(base.cylinder(30, 140, 54.9, 2.25, 5))
lid = lid.cut(keyhole).clean()
body = body.clean()
parts['body'], parts['lid'] = body, lid

out = ROOT / 'exports'
out.mkdir(exist_ok=True)
for name in ('speaker_bridge.stl', 'speaker_bridge.step'):
    (out / name).unlink(missing_ok=True)
checks = {}
meshes = {}
for name, part in parts.items():
    path = out / f'{name}.stl'
    cq.exporters.export(part, str(path), tolerance=0.05, angularTolerance=0.15)
    mesh = trimesh.load_mesh(path)
    assert part.val().isValid() and len(part.val().Solids()) == 1, name
    assert mesh.is_watertight and len(mesh.split()) == 1, name
    checks[name] = {'valid_cad': True, 'watertight_single_part': True}
    vertices, faces = part.val().tessellate(0.15, 0.2)
    meshes[name] = {'vertices': [list(v.toTuple()) for v in vertices],
                    'faces': faces, 'colour': '#a9c9bd', 'reference': False}

overlap = body.intersect(lid).val().Volume()
assert overlap < 0.001, overlap
checks['closed_lid_overlap_mm3'] = overlap
checks['part_overlaps_mm3'] = {}
for a, b in (('body','carrier'), ('lid','carrier')):
    volume = parts[a].intersect(parts[b]).val().Volume()
    assert volume < 0.001, (a, b, volume)
    checks['part_overlaps_mm3'][f'{a}/{b}'] = volume
checks['reference_overlaps_mm3'] = {}
for ref_name, ref in references.items():
    for part_name, part in parts.items():
        volume = part.intersect(ref).val().Volume()
        assert volume < 0.001, (part_name, ref_name, volume)
        checks['reference_overlaps_mm3'][f'{part_name}/{ref_name}'] = volume
for travel in (0, 1, 5, 10, 20, 45):
    volume = carrier.intersect(references['electronics_envelope'].translate((0, -travel, 0))).val().Volume()
    assert volume < 0.001, ('amplifier insertion', travel, volume)
checks['perfboard_rails_mm'] = {'board_width':20, 'channel_width':20.6,
    'contact_length':RAIL_LENGTH, 'lower_lip_thickness':1.6, 'upper_lip_thickness':UPPER_LIP,
    'channel_height':CHANNEL_TOP - CHANNEL_BOTTOM, 'stop_thickness':1.6,
    'closed_end_rail':True, 'end_rail_edge_overlap':0.7,
    'side_wall_thickness':1.4, 'board_top_faces_lid':True,
    'assembly_height_increase':PERFBOARD_RISE,
    'clearance_below_lower_lips':CHANNEL_BOTTOM - 1.6 - base.CARRIER_TOP,
    'electronics_top_to_lid':base.LID_BOTTOM - base.exact_bounds(references['electronics_envelope'])[5],
    'sampled_connected_assembly_insertion_clear':True}
assert checks['perfboard_rails_mm']['clearance_below_lower_lips'] >= 10 - 0.00001
assert checks['perfboard_rails_mm']['electronics_top_to_lid'] > 0
assert carrier.intersect(references['electronics_envelope'].translate((0, 0.5, 0))).val().Volume() > 0.1
checks['perfboard_rails_mm']['closed_end_blocks_overtravel'] = True
assert body.intersect(lid.translate((0, -1, 0))).val().Volume() > 0.1
checks['unsqueezed_latches_block_withdrawal'] = True
assert body.intersect(box(4.1, 0, 58.2, 51.8, 2, 1.8)).val().Volume() < 0.001

# Sample the insertion path with both noses squeezed inside the walls.
left_region = box(-1, -7, 55, 7.2, 40, 5).union(box(-1, -7, 55, 10, 6.7, 5))
right_region = left_region.mirror('YZ', (30, 0, 0))
left = lid.intersect(left_region)
right = lid.intersect(right_region)
centre = lid.cut(left_region).cut(right_region)
squeezed = centre.union(left.translate((1.6, 0, 0))).union(right.translate((-1.6, 0, 0)))
for travel in (0, 1, 5, 10, 25, 50, 100, 148):
    assert body.intersect(squeezed.translate((0, -travel, 0))).val().Volume() < 0.001, travel
checks['sampled_squeezed_insertion_path_clear'] = True
checks['latch_dimensions_mm'] = {'tongue_width': 3.0, 'tongue_thickness': 2.0,
    'slot_root_y': 36, 'slot_end_radius': 0.9, 'grip_extension_beyond_case': 0,
    'nose_straight_length':3, 'nose_sideways_engagement':1.4,
    'nose_thickness':2.2, 'release_travel':1.6}
checks['note'] = 'Review prototype. Tongue flexing, release access, print orientation and fit need a physical test.'
(out / 'checks.json').write_text(json.dumps(checks, indent=2) + '\n')
for name, part in references.items():
    vertices, faces = part.val().tessellate(0.3, 0.3)
    meshes[name] = {'vertices': [[round(x,3) for x in v.toTuple()] for v in vertices],
                    'faces': faces, 'colour':'#9483ab','reference':True}
compact = {name:{'vertices':[[round(x,3) for x in p] for p in mesh['vertices']],
                 'faces':mesh['faces']} for name,mesh in meshes.items()}
html = (ROOT / 'preview-template.html').read_text().replace(
    '__MESH_DATA__',json.dumps(compact,separators=(',',':')))
(ROOT / 'preview.html').write_text(html)
assembly = cq.Assembly(name='ALIVE enclosure')
for name, part in parts.items():
    assembly.add(part, name=name)
assembly.export(str(out / 'assembly.step'))
print(json.dumps(checks, indent=2))
