"""Shared enclosure dimensions and geometry in millimetres."""

import cadquery as cq
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box

WIDTH, LENGTH, DEPTH, WALL = 60.0, 150.0, 60.0, 2.0
LID_BOTTOM = 55.9

# Ruler measurements take precedence over scan estimates.
BATTERY_BOARD_L, BATTERY_WITH_USB_L, BATTERY_CONNECTED_L = 100.0, 106.0, 140.0
BATTERY_HOLE_D, BATTERY_HOLE_X = 3.0, 25.0
BATTERY_BOARD_W, BATTERY_HOLE_Y = 30.0, 95.0
BATTERY_BOARD_THICKNESS = 1.6
BOARD_X, BOARD_Y, BOARD_Z = 26.0, 6.0, 30.0
BOARD_CENTRE_X = BOARD_X + BATTERY_BOARD_W / 2
SWITCH_START, SWITCH_END = 82.0, 90.0
SWITCH_OPENING_DEPTH = 5.0
SWITCH_OPENING_Z = BOARD_Z + BATTERY_BOARD_THICKNESS

# The foam must touch only the outer fixed metal edge.
SPEAKER_D, SPEAKER_SEAT_INNER_D = 40.0, 39.0
SPEAKER_X, SPEAKER_Y = 30.0, 123.5
SPEAKER_RIM_Z, SPEAKER_BACK_Z, SPEAKER_BRIDGE_Z = 8.0, 26.0, 28.0
SPEAKER_FRONT_Z = 6.0
ELECTRONICS_X, ELECTRONICS_Y = 4.0, 56.0
ELECTRONICS_W, ELECTRONICS_L, ELECTRONICS_H = 20.0, 44.0, 25.0
ELECTRONICS_PCB_Z, ELECTRONICS_REAR_ALLOWANCE, ELECTRONICS_FRONT_ALLOWANCE = 37.0, 10.0, 18.0
ELECTRONICS_BOTTOM_Z = ELECTRONICS_PCB_Z - ELECTRONICS_REAR_ALLOWANCE
PERFBOARD_THICKNESS, AMPLIFIER_BOARD_THICKNESS, AMPLIFIER_GAP = 1.6, 1.6, 2.0
AMPLIFIER_HOLE_SPACING, AMPLIFIER_END_OFFSET = 13.0, 1.25
AMPLIFIER_END_OFFSET_RANGE = [1.0, 1.5]
AMPLIFIER_CLEARANCE_D, AMPLIFIER_PILOT_D = 2.6, 1.6
AMPLIFIER_SCREW_D, AMPLIFIER_SCREW_LENGTH = 2.0, 10.0
AMPLIFIER_HEAD_D, AMPLIFIER_HEAD_H, AMPLIFIER_SPACER_D = 4.0, 1.6, 4.0
AMPLIFIER_UNDERSIDE_Z = ELECTRONICS_PCB_Z + PERFBOARD_THICKNESS + AMPLIFIER_GAP
AMPLIFIER_TOP_Z = AMPLIFIER_UNDERSIDE_Z + AMPLIFIER_BOARD_THICKNESS
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


def amplifier_holes():
    return [(ELECTRONICS_X + ELECTRONICS_W / 2 + dx,
             ELECTRONICS_Y + ELECTRONICS_L - AMPLIFIER_END_OFFSET)
            for dx in (-AMPLIFIER_HOLE_SPACING / 2, AMPLIFIER_HOLE_SPACING / 2)]


def exact_bounds(part):
    # Ignore tessellation caches, which expand the default bounding box.
    bounds = Bnd_Box()
    BRepBndLib.AddOptimal_s(part.val().wrapped, bounds, False, False)
    return bounds.Get()


def build(*, include_speaker_bridge=True):
    body = box(0, 0, 0, WIDTH, LENGTH, DEPTH)
    body = body.cut(box(WALL, WALL, WALL, WIDTH - 2 * WALL, LENGTH - 2 * WALL, DEPTH))
    body = body.cut(box(WALL, -1, 55.6, WIDTH - 2 * WALL, WALL + 1, 5.4))
    for x in (WALL, WIDTH - WALL - 2):
        body = body.union(box(x, WALL, 54, 2, LENGTH - 2 * WALL, 1.6))
        body = body.union(box(x, WALL, 58.2, 2, LENGTH - 2 * WALL, 1.8))
    body = body.union(box(0, 0, 58.2, WIDTH, WALL, 1.8))
    body = body.cut(box(WIDTH - WALL - 1, BOARD_Y + SWITCH_START - 6, SWITCH_OPENING_Z,
                        WALL + 2, SWITCH_END - SWITCH_START + 12, SWITCH_OPENING_DEPTH))
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
        rib = box(8, SPEAKER_Y + offset - 0.9, 0, 44, 1.8, 3.0)
        body = body.union(rib.intersect(aperture))
    seat = cylinder(SPEAKER_X, SPEAKER_Y, WALL, 22.5, 5.5)
    seat = seat.cut(cylinder(SPEAKER_X, SPEAKER_Y, 1, SPEAKER_SEAT_INNER_D / 2, 8))
    body = body.union(seat)
    locator = cylinder(SPEAKER_X, SPEAKER_Y, 7.2, 22.5, 2.3)
    locator = locator.cut(cylinder(SPEAKER_X, SPEAKER_Y, 7, SPEAKER_D / 2 + 0.5, 3))
    body = body.union(locator)
    for x in ((2, 52) if include_speaker_bridge else ()):
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
    # Support the clear underside beneath the amplifier, clear of rear wire loops.
    for x, y in amplifier_holes():
        carrier = carrier.union(cylinder(x, y, CARRIER_TOP, 3,
                                         ELECTRONICS_PCB_Z - CARRIER_TOP))
        carrier = carrier.cut(cylinder(x, y, ELECTRONICS_PCB_Z - 6,
                                       AMPLIFIER_PILOT_D / 2, 7))
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

    board = box(BOARD_X, BOARD_Y, BOARD_Z, BATTERY_BOARD_W, BATTERY_BOARD_L, BATTERY_BOARD_THICKNESS)
    for x, y in holder_holes():
        board = board.cut(cylinder(x, y, BOARD_Z - 1, BATTERY_HOLE_D / 2, 4))
    cell = (cylinder(0, 0, 0, 9.25, 65).rotate((0, 0, 0), (1, 0, 0), -90)
            .translate((BOARD_CENTRE_X, BOARD_Y + 11, BOARD_Z + 11)))
    usb = box(BOARD_CENTRE_X - 7, BOARD_Y + 100, BOARD_Z + BATTERY_BOARD_THICKNESS, 14, 6, 7.5)
    bend = box(BOARD_CENTRE_X - 9, BOARD_Y + 106, BOARD_Z + BATTERY_BOARD_THICKNESS, 18, 34, 20)
    coil = cq.Workplane('XY').ellipse(COIL_W / 2, COIL_L / 2).extrude(COIL_H).translate((30, 53, 3))
    pcb = box(ELECTRONICS_X, ELECTRONICS_Y, ELECTRONICS_PCB_Z,
              ELECTRONICS_W, ELECTRONICS_L, PERFBOARD_THICKNESS)
    # End clearance notches may open into the edge at the measured 1 to 1.5 mm offset.
    for x, y in amplifier_holes():
        pcb = pcb.cut(cylinder(x, y, ELECTRONICS_PCB_Z - 1, AMPLIFIER_CLEARANCE_D / 2, 4))
        pcb = pcb.cut(box(x - AMPLIFIER_CLEARANCE_D / 2, y, ELECTRONICS_PCB_Z - 1,
                          AMPLIFIER_CLEARANCE_D, ELECTRONICS_Y + ELECTRONICS_L - y + 1, 4))
    electronics = pcb.union(box(5, 56, ELECTRONICS_BOTTOM_Z, 18, 30, ELECTRONICS_REAR_ALLOWANCE))
    electronics = electronics.union(box(5, 56, ELECTRONICS_PCB_Z + PERFBOARD_THICKNESS, 18, 28, 7))
    amplifier = box(4, 84, AMPLIFIER_UNDERSIDE_Z, 20, 16, AMPLIFIER_BOARD_THICKNESS)
    for x, y in amplifier_holes():
        amplifier = amplifier.cut(cylinder(x, y, AMPLIFIER_UNDERSIDE_Z - 1,
                                           AMPLIFIER_CLEARANCE_D / 2, 4))
    electronics = electronics.union(amplifier)
    electronics = electronics.union(box(8, 84, AMPLIFIER_TOP_Z, 12, 9, 3.8))
    electronics = electronics.union(box(10, 93, AMPLIFIER_TOP_Z, 8, 7,
                                         ELECTRONICS_PCB_Z + ELECTRONICS_FRONT_ALLOWANCE - AMPLIFIER_TOP_Z))
    spacers, fasteners = None, None
    for x, y in amplifier_holes():
        spacer = cylinder(x, y, ELECTRONICS_PCB_Z + PERFBOARD_THICKNESS,
                           AMPLIFIER_SPACER_D / 2, AMPLIFIER_GAP)
        spacer = spacer.cut(cylinder(x, y, ELECTRONICS_PCB_Z,
                                     AMPLIFIER_CLEARANCE_D / 2, 7))
        screw = cylinder(x, y, AMPLIFIER_TOP_Z - AMPLIFIER_SCREW_LENGTH,
                          AMPLIFIER_SCREW_D / 2, AMPLIFIER_SCREW_LENGTH)
        screw = screw.union(cylinder(x, y, AMPLIFIER_TOP_Z, AMPLIFIER_HEAD_D / 2, AMPLIFIER_HEAD_H))
        spacers = spacer if spacers is None else spacers.union(spacer)
        fasteners = screw if fasteners is None else fasteners.union(screw)
    electronics_usb = box(8, 20, ELECTRONICS_PCB_Z + PERFBOARD_THICKNESS, 12, 36, 8)
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
        'usb_port_envelope': usb, 'plug_bend_space': bend, 'electronics_plug_space': electronics_usb,
        'electronics_spacers': spacers, 'electronics_fasteners': fasteners}
