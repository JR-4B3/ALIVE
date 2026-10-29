# ALIVE enclosure

This is the current print version. One enclosure needs three STL files: `body.stl`, `lid.stl` and `carrier.stl`. The speaker bridge and its two supports are removed. The original circular speaker seat stays in place.

## Perfboard rails

The two amplifier screw posts are replaced by paired rails on the carrier. The channel accepts the nominal 20 mm wide, 1.6 mm thick brown perfboard, with its components facing the lid. It has 20.6 mm inside width, 2.2 mm inside height and 15 mm contact length. The lower lips are 1.6 mm thick and the upper lips are 1.4 mm thick to fit below the amplifier PCB. The side walls are 1.4 mm thick to preserve clearance to the case wall and battery holder. A third grooved rail joins the far ends into a U-shaped holder. Its rear wall is 1.6 mm thick, with upper and lower lips that overlap the perfboard end by 0.7 mm. The insertion end remains open. The end rail spans the 20.6 mm channel, so review its bridging or support needs in the slicer.

The assembly sits 0.8 mm higher than before. This provides 10 mm below the lower lips and 11.8 mm below the perfboard for rear wiring. The conservative electronics envelope has only 0.1 mm clearance to the closed lid. Check the new carrier on the actual assembly before further prints.

Insert the connected electronics assembly along the rails before fastening the carrier if the wiring restricts access. The amplifier screws, screw posts and separate spacers are no longer used. Do not cut new notches in the brown board for this mount.

## Lid retention

The body has no crossbar above the insertion opening. Two windows receive noses on the lid's flexible side tongues. The tongues are 3 mm wide and 2 mm thick. Their slots end at Y 36 mm with a 0.9 mm end radius.

Each nose retains its 3 mm straight section, followed by a lead-in ramp. Its sideways engagement into the case wall is 1.4 mm, increased from 0.85 mm. The nose is 2.2 mm thick and remains recessed 0.6 mm from the case exterior. A 1.6 mm inward movement clears it. There are no projecting grip pads.

Press both noses inward through the side windows and slide the lid out. Confirm release force and repeated flexing with a printed test.

## Checks and regeneration

`exports/checks.json` records valid single-solid CAD, connected watertight STL exports, printed-part and reference-shape clearances, sampled amplifier insertion and lid release paths, and nominal rail and latch dimensions. The insertion checks do not model wire bending, complete pin geometry, elastic flexing or strength.

Install the pinned dependencies and run the current generator:

```sh
python3 -m pip install -r requirements.txt
python3 enclosure.py
```

`enclosure.py` uses the dimensions and base geometry in `base_geometry.py`. It regenerates the three STL files, `exports/assembly.step`, `exports/checks.json` and `preview.html`. `preview-template.html` contains the viewer controls and assembly notes. Open `preview.html` to inspect the parts and assembly steps.

The earlier screw-post design, speaker bridge, duplicate variant exports and old paper template are archived outside the repository. The exported files here are the current side-latch design after the first physical fit test.
