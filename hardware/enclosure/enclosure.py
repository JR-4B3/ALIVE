"""Build the ALIVE enclosure prototype. All dimensions are in millimetres."""

import json
from pathlib import Path
import cadquery as cq
import trimesh
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box

ROOT = Path(__file__).parent
OUT = ROOT / 'exports'
WIDTH, LENGTH, DEPTH, WALL = 60.0, 150.0, 60.0, 2.0
LID_BOTTOM = 55.9

# Ruler measurements take precedence over scan estimates.
BATTERY_BOARD_L, BATTERY_WITH_USB_L, BATTERY_CONNECTED_L = 100.0, 106.0, 140.0
BATTERY_HOLE_D, BATTERY_HOLE_X = 3.0, 25.0
BATTERY_BOARD_W, BATTERY_HOLE_Y = 30.0, 95.0
BOARD_X, BOARD_Y, BOARD_Z = 26.0, 6.0, 30.0
BOARD_CENTRE_X = BOARD_X + BATTERY_BOARD_W / 2
SWITCH_START, SWITCH_END = 82.0, 90.0

# The foam must touch only the outer fixed metal edge.
SPEAKER_D, SPEAKER_SEAT_INNER_D = 40.0, 39.0
SPEAKER_X, SPEAKER_Y = 30.0, 123.5
SPEAKER_RIM_Z, SPEAKER_BACK_Z, SPEAKER_BRIDGE_Z = 8.0, 26.0, 28.0
SPEAKER_FRONT_Z = 6.0
ELECTRONICS_X, ELECTRONICS_Y = 4.0, 56.0
ELECTRONICS_W, ELECTRONICS_L, ELECTRONICS_H = 20.0, 44.0, 25.0
ELECTRONICS_PCB_Z, ELECTRONICS_BOTTOM_Z = 35.0, 28.0
COIL_W, COIL_L, COIL_H = 50.0, 80.0, 19.0
CARRIER_BOTTOM, CARRIER_TOP = 24.0, 26.0
CARRIER_SCREWS = [(6.0, 8.0), (53.0, 18.0), (6.0, 106.0), (54.0, 114.0)]
WALL_MOUNT_X, WALL_MOUNT_ENTRY_Y, WALL_MOUNT_SEAT_Y = WIDTH / 2, 130.0, 140.0
WALL_MOUNT_ENTRY_D, WALL_MOUNT_SLOT_W = 9.0, 4.5
WALL_SCREW_HEAD_D, WALL_SCREW_HEAD_H, WALL_SCREW_SHAFT_D = 8.0, 3.0, 4.0


def box(x, y, z, w, length, h):
    return cq.Workplane('XY').box(w, length, h, centered=False).translate((x, y, z))


def cylinder(x, y, z, radius, height):
    return cq.Workplane('XY').circle(radius).extrude(height).translate((x, y, z))


def cone(x, y, z, r1, r2, height):
    solid = cq.Solid.makeCone(r1, r2, height, cq.Vector(x, y, z), cq.Vector(0, 0, 1))
    return cq.Workplane('XY').newObject([solid])


def tie_anchor(x, y, z, width=3.0):
    return box(x, y, z, width, 8, 6).cut(box(x - 1, y + 2, z + 1, width + 2, 4, 3))


def holder_holes():
    return [(BOARD_CENTRE_X + dx, BOARD_Y + dy)
            for dx in (-BATTERY_HOLE_X / 2, BATTERY_HOLE_X / 2)
            for dy in ((BATTERY_BOARD_L - BATTERY_HOLE_Y) / 2,
                       (BATTERY_BOARD_L + BATTERY_HOLE_Y) / 2)]


def exact_bounds(part):
    # Ignore tessellation caches, which expand the default bounding box.
    bounds = Bnd_Box()
    BRepBndLib.AddOptimal_s(part.val().wrapped, bounds, False, False)
    return bounds.Get()


def build():
    body = box(0, 0, 0, WIDTH, LENGTH, DEPTH)
    body = body.cut(box(WALL, WALL, WALL, WIDTH - 2 * WALL, LENGTH - 2 * WALL, DEPTH))
    body = body.cut(box(WALL, -1, 55.6, WIDTH - 2 * WALL, WALL + 1, 5.4))
    for x in (WALL, WIDTH - WALL - 2):
        body = body.union(box(x, WALL, 54, 2, LENGTH - 2 * WALL, 1.6))
        body = body.union(box(x, WALL, 58.2, 2, LENGTH - 2 * WALL, 1.8))
    body = body.union(box(0, 0, 58.2, WIDTH, WALL, 1.8))
    body = body.cut(box(57, BOARD_Y + SWITCH_START - 6, BOARD_Z - 4,
                        4, SWITCH_END - SWITCH_START + 12, 16))
    # Corner supports leave the coil space open below the removable tray.
    for x, y in CARRIER_SCREWS:
        start_x, w = (2, 8) if x < 30 else (49, 9)
        if x > 30 and y > 110:
            start_x, w = 51, 7
        body = body.union(box(start_x, y - 4, WALL, w, 8, CARRIER_BOTTOM - WALL))
        body = body.cut(cylinder(x, y, 16, 1.1, CARRIER_BOTTOM - 16 + 1))
    for x in (2, 55):
        body = body.union(tie_anchor(x, 49, WALL))
    body = body.union(tie_anchor(45, 94, WALL, 4))

    # The grille is in front of the cone with a separate air gap.
    aperture = cylinder(SPEAKER_X, SPEAKER_Y, -1, 19, 4)
    body = body.cut(aperture)
    for offset in (-14, -7, 0, 7, 14):
        rib = box(8, SPEAKER_Y + offset - 0.6, 0, 44, 1.2, WALL)
        body = body.union(rib.intersect(aperture))
    seat = cylinder(SPEAKER_X, SPEAKER_Y, WALL, 22.5, 5.5)
    seat = seat.cut(cylinder(SPEAKER_X, SPEAKER_Y, 1, SPEAKER_SEAT_INNER_D / 2, 8))
    body = body.union(seat)
    locator = cylinder(SPEAKER_X, SPEAKER_Y, 7.2, 22.5, 2.3)
    locator = locator.cut(cylinder(SPEAKER_X, SPEAKER_Y, 7, SPEAKER_D / 2 + 0.5, 3))
    body = body.union(locator)
    for x in (2, 52):
        body = body.union(box(x, SPEAKER_Y - 4, WALL, 6, 8, SPEAKER_BRIDGE_Z - WALL))
        body = body.cut(cylinder(x + 3, SPEAKER_Y, 20, 1.1, 10))

    carrier = box(2.5, 3.5, CARRIER_BOTTOM, 55, 106.5, 2)
    carrier = carrier.union(box(49, 109, CARRIER_BOTTOM, 8.5, 9, 2))
    carrier = carrier.cut(box(4, 14, 23, 20, 36, 4))
    carrier = carrier.cut(box(17, 102, 23, 8, 10, 4))
    for x, y in CARRIER_SCREWS:
        carrier = carrier.cut(cylinder(x, y, 23, 1.4, 5))
        carrier = carrier.cut(cone(x, y, 24.7, 1.4, 2.7, 1.3))
    for x, y in holder_holes():
        carrier = carrier.union(cylinder(x, y, CARRIER_TOP, 3, BOARD_Z - CARRIER_TOP))
        # Keep the pilot open at the top when the post height changes.
        carrier = carrier.cut(cylinder(x, y, 24.6, 1.1, BOARD_Z - 24.6 + 1))
    # The perfboard rests on its bare edges, above underside joints.
    for x, width in ((2.5, 2), (23.5, 1)):
        carrier = carrier.union(box(x, ELECTRONICS_Y, CARRIER_TOP, width, ELECTRONICS_L,
                                    ELECTRONICS_PCB_Z - CARRIER_TOP))
    for x, width in ((2.5, 1.3), (24.2, 0.8)):
        carrier = carrier.union(box(x, ELECTRONICS_Y, ELECTRONICS_PCB_Z, width, ELECTRONICS_L, 2))
    # Verify a bare perfboard strip beneath the strap before assembly.
    for x in (2.5, 24.2):
        carrier = carrier.union(tie_anchor(x, 78, ELECTRONICS_PCB_Z + 2, 1.3))
    carrier = carrier.union(tie_anchor(26, 106, CARRIER_TOP, 4))

    bridge = box(2, SPEAKER_Y - 3.5, SPEAKER_BRIDGE_Z, 56, 7, 2.4)
    for x in (5, 55):
        bridge = bridge.cut(cylinder(x, SPEAKER_Y, 27, 1.4, 5))
    lid = box(2.3, 0.3, LID_BOTTOM, WIDTH - 4.6, LENGTH - 2.6, 2)
    for x in (23.2, 36):
        lid = lid.cut(box(x, 0.2, 55, 0.8, 23.8, 5))
    lid = lid.cut(box(23.2, 0.2, 55, 13.6, 1.1, 5))
    ramp = (cq.Workplane('YZ').polyline([(2.5, 57.8), (2.5, 59.1), (3.6, 59.1), (5.5, 57.8)])
            .close().extrude(12).translate((24, 0, 0)))
    lid = lid.union(ramp)
    for y in (8, 11, 14):
        lid = lid.cut(box(26, y, 57.6, 8, 0.8, 0.5))
    # Lower the upright case to seat the screw shaft in the narrow upper slot.
    keyhole = cylinder(WALL_MOUNT_X, WALL_MOUNT_ENTRY_Y, LID_BOTTOM - 1,
                       WALL_MOUNT_ENTRY_D / 2, 5)
    keyhole = keyhole.union(box(WALL_MOUNT_X - WALL_MOUNT_SLOT_W / 2, WALL_MOUNT_ENTRY_Y,
                               LID_BOTTOM - 1, WALL_MOUNT_SLOT_W,
                               WALL_MOUNT_SEAT_Y - WALL_MOUNT_ENTRY_Y, 5))
    keyhole = keyhole.union(cylinder(WALL_MOUNT_X, WALL_MOUNT_SEAT_Y, LID_BOTTOM - 1,
                                    WALL_MOUNT_SLOT_W / 2, 5))
    lid = lid.cut(keyhole)

    board = box(BOARD_X, BOARD_Y, BOARD_Z, BATTERY_BOARD_W, BATTERY_BOARD_L, 1.6)
    for x, y in holder_holes():
        board = board.cut(cylinder(x, y, BOARD_Z - 1, BATTERY_HOLE_D / 2, 4))
    cell = (cylinder(0, 0, 0, 9.25, 65).rotate((0, 0, 0), (1, 0, 0), -90)
            .translate((BOARD_CENTRE_X, BOARD_Y + 11, BOARD_Z + 11)))
    usb = box(BOARD_CENTRE_X - 7, BOARD_Y + 100, BOARD_Z + 1.6, 14, 6, 7.5)
    bend = box(BOARD_CENTRE_X - 9, BOARD_Y + 106, BOARD_Z + 1.6, 18, 34, 20)
    coil = cq.Workplane('XY').ellipse(COIL_W / 2, COIL_L / 2).extrude(COIL_H).translate((30, 53, 3))
    pcb = box(ELECTRONICS_X, ELECTRONICS_Y, ELECTRONICS_PCB_Z, 20, 44, 1.6)
    electronics = pcb.union(box(5, 58, ELECTRONICS_BOTTOM_Z, 18, 40, 7))
    electronics = electronics.union(box(5, 56, 36.6, 18, 24, 7))
    electronics = electronics.union(box(4, 84, 36.6, 20, 16, 7.4))
    electronics = electronics.union(box(10, 93, 44, 8, 7, 9))
    electronics_usb = box(8, 20, 36.6, 12, 36, 8)
    rim = cylinder(SPEAKER_X, SPEAKER_Y, SPEAKER_RIM_Z, SPEAKER_D / 2, 0.8)
    rim = rim.cut(cylinder(SPEAKER_X, SPEAKER_Y, 7, 18.8, 3))
    speaker = rim.union(cone(SPEAKER_X, SPEAKER_Y, 8.8, 19, 15, 12.2))
    speaker = speaker.union(cylinder(SPEAKER_X, SPEAKER_Y, 21, 7.5, 5))
    speaker = speaker.union(cone(SPEAKER_X, SPEAKER_Y, SPEAKER_FRONT_Z, 5, 18.9, 2))
    speaker_pad = box(25, SPEAKER_Y - 3.5, SPEAKER_BACK_Z, 10, 7, 2)
    return {'body': body.clean(), 'lid': lid.clean(), 'carrier': carrier.clean(),
            'speaker_bridge': bridge.clean()}, {
        'battery_board': board, 'battery_cell': cell, 'electronics_envelope': electronics,
        'speaker_envelope': speaker, 'speaker_pad': speaker_pad, 'cable_space': coil,
        'usb_port_envelope': usb, 'plug_bend_space': bend, 'electronics_plug_space': electronics_usb}


def main():
    OUT.mkdir(exist_ok=True)
    parts, references = build()
    checks, meshes = {}, {}
    colours = {'body': '#b5c2ce', 'lid': '#8c9eaf', 'carrier': '#94a99c', 'speaker_bridge': '#91a6b9',
        'battery_board': '#4e746a', 'battery_cell': '#bb8962', 'electronics_envelope': '#7b68a1',
        'speaker_envelope': '#293847', 'speaker_pad': '#92908d', 'cable_space': '#4a97b6',
        'usb_port_envelope': '#9b9c9d', 'plug_bend_space': '#c7943d', 'electronics_plug_space': '#c7943d'}
    for name, part in {**parts, **references}.items():
        shape = part.val()
        vertices, faces = shape.tessellate(0.15, 0.2)
        meshes[name] = {'vertices': [[round(v.x,4),round(v.y,4),round(v.z,4)] for v in vertices],
                        'faces': faces, 'colour': colours[name], 'reference': name in references}
        if name not in parts:
            continue
        stl, step = OUT / f'{name}.stl', OUT / f'{name}.step'
        cq.exporters.export(part, str(stl), tolerance=0.05, angularTolerance=0.15)
        cq.exporters.export(part, str(step))
        mesh = trimesh.load_mesh(stl)
        imported = cq.importers.importStep(str(step)).val()
        checks[name] = {'valid_cad': shape.isValid(), 'solid_count': len(shape.Solids()),
            'stl_watertight': bool(mesh.is_watertight), 'stl_connected_parts': len(mesh.split()),
            'stl_dimensions_mm': mesh.extents.round(3).tolist(), 'step_valid': imported.isValid(),
            'step_volume_error_mm3': abs(imported.Volume()-shape.Volume())}
        assert checks[name]['valid_cad'] and checks[name]['solid_count']==1, name
        assert checks[name]['stl_watertight'] and checks[name]['stl_connected_parts']==1, name
        assert checks[name]['step_valid'] and checks[name]['step_volume_error_mm3']<0.01, name
    checks['printed_part_overlaps_mm3'] = {}
    names = list(parts)
    for i,a in enumerate(names):
        for b in names[i+1:]:
            volume = parts[a].intersect(parts[b]).val().Volume()
            checks['printed_part_overlaps_mm3'][f'{a}/{b}'] = round(volume,6)
            assert volume<0.001, f'{a} intersects {b}'
    checks['component_mount_overlaps_mm3'] = {}
    for name,reference in references.items():
        for part_name,part in parts.items():
            volume = part.intersect(reference).val().Volume()
            checks['component_mount_overlaps_mm3'][f'{name}/{part_name}'] = round(volume,6)
            assert volume<0.001, f'{name} intersects {part_name}'
    checks['component_pair_overlaps_mm3'] = {}
    for a,b in [('battery_board','electronics_envelope'),('battery_cell','electronics_envelope'),
                ('cable_space','electronics_envelope'),('speaker_envelope','plug_bend_space'),
                ('electronics_plug_space','battery_board'),('electronics_plug_space','battery_cell')]:
        volume = references[a].intersect(references[b]).val().Volume()
        checks['component_pair_overlaps_mm3'][f'{a}/{b}'] = round(volume,6)
        assert volume<0.001, f'{a} intersects {b}'
    checks['reference_bounds_mm'] = {}
    for name,expected in [('speaker_envelope',(40,40,20)),('electronics_envelope',(20,44,25))]:
        xmin,ymin,zmin,xmax,ymax,zmax = exact_bounds(references[name])
        actual = [xmax-xmin,ymax-ymin,zmax-zmin]
        assert all(abs(a-b)<0.00001 for a,b in zip(actual,expected)), name
        checks['reference_bounds_mm'][name] = actual
    # Check a straight lift through the open back, without the lid or holder contacts.
    xmin,ymin,zmin,xmax,ymax,zmax = exact_bounds(references['battery_cell'])
    sweep = box(xmin,ymin,zmin,xmax-xmin,ymax-ymin,DEPTH-zmin+20)
    checks['battery_removal_sweep_overlaps_mm3'] = {}
    for name,obstacle in {**parts,'electronics':references['electronics_envelope'],
                          'speaker':references['speaker_envelope']}.items():
        if name == 'lid':
            continue
        volume = sweep.intersect(obstacle).val().Volume()
        checks['battery_removal_sweep_overlaps_mm3'][name] = round(volume,6)
        assert volume<0.001, f'Battery extraction intersects {name}'
    head_z = LID_BOTTOM - WALL_SCREW_HEAD_H
    head_sweep = cylinder(WALL_MOUNT_X, WALL_MOUNT_ENTRY_Y, head_z,
                          WALL_SCREW_HEAD_D / 2, WALL_SCREW_HEAD_H)
    head_sweep = head_sweep.union(box(WALL_MOUNT_X - WALL_SCREW_HEAD_D / 2,
                                     WALL_MOUNT_ENTRY_Y, head_z, WALL_SCREW_HEAD_D,
                                     WALL_MOUNT_SEAT_Y - WALL_MOUNT_ENTRY_Y, WALL_SCREW_HEAD_H))
    head_sweep = head_sweep.union(cylinder(WALL_MOUNT_X, WALL_MOUNT_SEAT_Y, head_z,
                                          WALL_SCREW_HEAD_D / 2, WALL_SCREW_HEAD_H))
    entry_sweep = cylinder(WALL_MOUNT_X, WALL_MOUNT_ENTRY_Y, head_z,
                           WALL_SCREW_HEAD_D / 2, DEPTH + 2 - head_z)
    shaft = cylinder(WALL_MOUNT_X, WALL_MOUNT_SEAT_Y, LID_BOTTOM,
                     WALL_SCREW_SHAFT_D / 2, DEPTH + 2 - LID_BOTTOM)
    checks['wall_mount_overlaps_mm3'] = {}
    for motion_name,motion in [('head_insertion',entry_sweep),('head_seating',head_sweep),
                               ('seated_shaft',shaft)]:
        for name,obstacle in {**parts,**references}.items():
            volume = motion.intersect(obstacle).val().Volume()
            checks['wall_mount_overlaps_mm3'][f'{motion_name}/{name}'] = round(volume,6)
            assert volume<0.001, f'Wall screw {motion_name} intersects {name}'
    # The narrow slot retains the head at the upper seat.
    head_at_seat = cylinder(WALL_MOUNT_X, WALL_MOUNT_SEAT_Y, LID_BOTTOM, 3, 2)
    assert parts['lid'].intersect(head_at_seat).val().Volume()>0
    checks['wall_mount_mm'] = {'entry_diameter':WALL_MOUNT_ENTRY_D,
        'slot_width':WALL_MOUNT_SLOT_W,'entry_centre':[WALL_MOUNT_X,WALL_MOUNT_ENTRY_Y],
        'upper_seat_centre':[WALL_MOUNT_X,WALL_MOUNT_SEAT_Y],
        'minimum_head_diameter':6,'maximum_head_diameter':WALL_SCREW_HEAD_D,
        'maximum_head_thickness':WALL_SCREW_HEAD_H,
        'maximum_shaft_diameter':WALL_SCREW_SHAFT_D,
        'wall_to_head_underside_when_seated':DEPTH-LID_BOTTOM,
        'head_to_holder_plug_space':head_z-(BOARD_Z+1.6+20)}
    checks['measured_dimensions_mm'] = {'holder_without_usb':100,'holder_with_usb':106,
        'holder_with_current_plug_and_bend':140,'board_hole_diameter':3,
        'approximate_transverse_hole_centre_spacing':25,'longitudinal_hole_spacing':95,
        'switch_position_from_bottom':[82,90],'speaker_outer_diameter':40,'speaker_total_depth':20,
        'speaker_rear_step_diameter':30,'speaker_rim_to_rear_step':13,
        'speaker_magnet_diameter':15,'speaker_magnet_depth':5,'electronics_maximum':[44,20,25]}
    checks['provisional_dimensions_mm'] = {'holder_width':30,
        'speaker_seat_inner_diameter':SPEAKER_SEAT_INNER_D,
        'speaker_front_projection_inferred':SPEAKER_RIM_Z-SPEAKER_FRONT_Z,
        'electronics_height_above_pcb':18,'electronics_underside_allowance':7,
        'coil_oval_width_length_height':[COIL_W,COIL_L,COIL_H]}
    checks['clearances_mm'] = {'current_holder_plug_end_to_wall':LENGTH-WALL-(BOARD_Y+140),
        'cone_to_grille':SPEAKER_FRONT_Z-WALL,'coil_top_to_carrier':CARRIER_BOTTOM-(3+COIL_H),
        'electronics_top_to_closed_lid':LID_BOTTOM-(ELECTRONICS_BOTTOM_Z+ELECTRONICS_H),
        'battery_top_to_closed_lid':LID_BOTTOM-(BOARD_Z+11+9.25),
        'speaker_bridge_to_holder_plug':BOARD_Z+1.6-(SPEAKER_BRIDGE_Z+2.4)}
    assert min(checks['clearances_mm'].values())>0
    checks['status'] = 'Prototype. Verify speaker rim contact, bare perfboard strap contact, mounting dimensions and final cable fit before ordering.'
    (OUT/'checks.json').write_text(json.dumps(checks,indent=2)+'\n')
    template = (ROOT/'preview-template.html').read_text()
    (ROOT/'preview.html').write_text(template.replace('__MESH_DATA__',json.dumps(meshes,separators=(',',':'))))
    assembly = cq.Assembly(name='ALIVE enclosure')
    for name,part in parts.items():
        assembly.add(part,name=name)
    assembly.export(str(OUT/'assembly.step'))
    print(json.dumps(checks,indent=2))


if __name__ == '__main__':
    main()
