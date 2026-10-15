# ALIVE enclosure

A 150 × 60 × 60 mm enclosure for the 18650 holder, soldered ESP and amplifier assembly, speaker and USB cable. The sliding back lid gives tool-free battery access. The internal mounts and cable anchors protect the solder joints during handling and battery changes.

This version is a fit prototype. Print one complete enclosure before making more. The 65 mm outside width discussed as an alternative has not been implemented.

## Files

- `exports/` contains four STL parts, `assembly.step` and `checks.json`. Each STL uses millimetres. One complete enclosure needs one `body.stl`, one `lid.stl`, one `carrier.stl` and one `speaker_bridge.stl`.
- `enclosure.py` is the editable CadQuery model and verification script.
- `preview.html` shows the CAD meshes with simplified component volumes. Open it in a browser to rotate the model and hide layers. `preview-template.html` is its source template.
- `paper-fit-check.pdf` is an A4 footprint check. Print at 100 percent and measure its 100 mm scale bar. `make_fit_template.py` regenerates it.

Use the four separate STL files for a printing quote. `assembly.step` shows the printed parts in their assembled positions and is for CAD review.

## Dimensions

Ruler measurements take priority over the approximate iPhone scans supplied on 15 October 2026.

| Part | Dimensions used |
| --- | --- |
| Battery holder | 100 mm board length, 106 mm including USB-A socket, 140 mm including the current connected plug and cable bend |
| Holder mounting holes | 3 mm diameter, about 25 mm transverse and confirmed 95 mm longitudinal centre spacing |
| Holder switch | Right side with USB pointing up, 82 to 90 mm from the opposite bottom end |
| Speaker | 40 mm outside metal rim diameter, 20 mm total depth |
| Speaker rear profile | 30 mm rear step diameter at 13 mm behind the rim, then a 15 mm magnet diameter with 5 mm additional depth |
| Electronics assembly | Approximately 44 × 20 × 25 mm, including solder and terminal block |
| Reserved cable coil | An unverified 80 × 50 × 19 mm oval space |

The holder width is about 30 mm from the scans. The 60 mm case has 2 mm walls and 56 mm inside width. The electronics and holder have nominal 2 mm gaps at both outer sides and between their width envelopes. Mounts occupy some of those gaps. The wider holder scan leaves about 1 mm at the right wall, so measurement error matters.

The electronics reference reserves 7 mm below the PCB and 18 mm above its underside. Its highest point is 2.9 mm below the closed lid. The current holder plug and bend end 2 mm before the inside upper wall.

The speaker depths imply about 2 mm forward projection, which is inferred. The nominal moving-cone clearance to the grille is 4 mm. The speaker seat has a 39 mm opening and a locating collar with 0.5 mm radial clearance around the 40 mm frame.

The scans omit small details and some undersides. The electronics scan underestimated its total height at 19 mm, which the ruler measurement corrected to 25 mm. The current folded cable region in the connected scan occupies roughly 95 × 60 × 27 mm. Re-coiling it into the reserved oval remains unverified. The ordered [USB cable](https://de.aliexpress.com/item/1005009431718646.html) has no verified plug or cable thickness in this model.

## Mounting and assembly

The holder sits on the right, with its cell facing the sliding back. The intact electronics assembly sits on the left. A removable tray separates both boards from the cable coil near the front. The speaker sits behind the grille at the upper end.

The holder uses four mounting posts. The electronics rest on bare perfboard edges. A strap crosses an assumed bare strip between the ESP and amplifier. Check this contact area before tightening the strap, and move the loops in the source if components or solder occupy it.

Fit a soft gasket about 0.5 mm thick between the outer fixed metal speaker rim and its seat. Nominal radial overlap is only 0.5 mm. The bridge holds a 10 × 7 mm soft pad against the rear magnet, about 2 mm thick after compression. Adjust the pad to remove play without bending the frame. Keep all supports and foam clear of the flexible surround, cone and dome.

Initial assembly uses small screws, soft pads and cable ties or reusable straps. The printed pilot holes are 2.2 mm and clearance holes are 2.8 mm, provisionally for screws around M2.5. Carrier screws have shallow countersinks. Choose screw type, head size and length with the printer. Screw heads are absent from the collision checks.

1. Fit the gasket and speaker, then install the padded bridge.
2. Thread the USB connectors through the tray openings. Restrain the coil below the tray and leave relaxed bends at both ends.
3. Fasten the tray, holder and electronics. Tighten the electronics strap only against verified bare board areas.
4. Restrain insulated speaker leads near the tray edge. Leave slack at solder joints and keep wires clear of the lid rails and switch.
5. Fit a fabric pull ribbon under the battery. Check that the cell lifts out with the mounts fixed and that the side switch is accessible.
6. Close the lid and test the project, including audio output, ALIVE reception and wireless connection with the cable coiled inside.

## Wall mounting

The back lid has one keyhole slot near the upper end. Its lower entry is 9 mm in diameter, with a 4.5 mm wide slot leading to a seat 10 mm above the entry. Hang the case upright with the speaker at the top. Push the larger opening over a headed wall fastener, then lower the case to seat its shaft in the narrow slot.

Choose a fastener suitable for the wall with a shaft no wider than 4 mm, a head about 6 to 8 mm across and no thicker than 3 mm. The recessed lid needs about 4.1 mm between the wall and the underside of the seated head, plus a little sliding clearance. Adjust the fastener depth for a fit that lifts off without force. The head path has nominal 1.3 mm clearance to the assumed USB plug space. Keep the cable out of this path and verify the actual fastener against the prototype.

Lift the complete case off the wall before opening the back for a battery change. With the case upright, the lid's upper edge rests against the body's closed upper end. Test the printed keyhole, lid retention and fastener with the assembled case before leaving it hanging. This is a mounting prototype without a tested load rating.

## Printing and remaining checks

PETG FDM is the intended starting process. Ask the printer to review the body rails, overhangs, support removal and thin strap loops. Start the body with its front on the bed, and print the tray and bridge flat. The lid needs an orientation review because the latch projects beyond its back face.

The lid has 0.3 mm nominal clearance above and below. Its fit, release force and repeated flexing need a printed test. Ask for a dry fit of the printed parts. Scaling the entire model would also change the component mounts.

Before more prints, check final cable fit, speaker gasket contact, electronics support and strap contact, screw clearance, switch reach and battery removal. The grille and enclosure can change acoustic output, so check the assembled project.

`exports/checks.json` records CAD validity, one connected watertight STL per part, STEP round trips, simplified component bounds, selected collisions and nominal clearances. It also checks a straight battery removal path with the lid removed and the wall fastener's insertion and seating paths. These checks do not model the holder contacts, complete wiring, assembly screws, mounting strength or actual printed tolerances.

## Rebuild

Use Python 3.11 or newer in an isolated environment. Install the packages from `requirements.txt`, then run from the repository root:

```bash
python -m pip install -r hardware/enclosure/requirements.txt
python hardware/enclosure/enclosure.py
python hardware/enclosure/make_fit_template.py
```

The scripts regenerate `exports/`, `preview.html` and the paper template. The first script stops if its geometric checks fail. It also exports and verifies a separate STEP file for each part locally. Git stores the assembled STEP once to avoid duplicate CAD files. Raw scans, temporary analysis files, correspondence and price estimates stay outside this branch.
