"""Create a dimensioned A4 sheet for checking the proposed footprints at full scale."""

from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle, Ellipse
from enclosure import BOARD_X, BOARD_Y, BOARD_CENTRE_X, SPEAKER_D, holder_holes

ROOT = Path(__file__).parent
fig = plt.figure(figsize=(210 / 25.4, 297 / 25.4))
ax = fig.add_axes([0, 0, 1, 1])
ax.set(xlim=(0, 210), ylim=(0, 297), aspect='equal')
ax.axis('off')
ax.text(15, 282, 'ALIVE enclosure, paper fit check', fontsize=13)
ax.text(15, 274, 'Print at 100%. Disable fit-to-page scaling. Measure the 100 mm bar first.', fontsize=8)
for origin, title in [(20, 'Rear layer'), (120, 'Front layer')]:
    ax.add_patch(Rectangle((origin, 105), 60, 150, fill=False, lw=1))
    ax.add_patch(Rectangle((origin + 2, 107), 56, 146, fill=False, lw=.5, ls='--'))
    ax.text(origin, 260, title, fontsize=10)
    ax.text(origin, 98, '60 mm outside width', fontsize=8)
ax.add_patch(Rectangle((20 + BOARD_X, 105 + BOARD_Y), 30, 100, fill=False, ec='#51806a', lw=1))
for x, y in holder_holes():
    ax.add_patch(Circle((20 + x, 105 + y), 1.5, fill=False, ec='#51806a', lw=.7))
    ax.plot([20 + x - 2, 20 + x + 2], [105 + y, 105 + y], color='#51806a', lw=.3)
ax.text(20 + BOARD_CENTRE_X, 150, 'Holder', ha='center', rotation=90, fontsize=9, color='#386950')
ax.add_patch(Rectangle((24, 161), 20, 44, fill=False, ec='#80679a', lw=1))
ax.text(34, 182, 'Electronics', ha='center', rotation=90, fontsize=8, color='#75578e')
ax.add_patch(Rectangle((20 + BOARD_CENTRE_X - 7, 211), 14, 6, fill=False, ec='#666666', lw=.7))
ax.add_patch(Rectangle((20 + BOARD_CENTRE_X - 9, 217), 18, 34, fill=False, ec='#ac782b', ls='--', lw=.7))
ax.add_patch(Ellipse((150, 158), 50, 80, fill=False, ec='#3486a7', lw=1))
ax.text(150, 158, 'Coil space', ha='center', fontsize=9, color='#3486a7')
ax.text(150, 151, '80 × 50 mm oval', ha='center', fontsize=8, color='#3486a7')
ax.add_patch(Circle((150, 228.5), SPEAKER_D / 2, fill=False, ec='#333333', lw=1))
ax.text(150, 228.5, 'Speaker', ha='center', fontsize=9)
ax.text(150, 219, f'{SPEAKER_D:g} mm outer rim', ha='center', fontsize=7)
ax.plot([20, 120], [80, 80], color='black', lw=1)
for mm in range(0, 101, 10):
    ax.plot([20 + mm] * 2, [78, 82], color='black', lw=.6)
    ax.text(20 + mm, 74, str(mm), ha='center', fontsize=6)
ax.text(20, 86, 'This bar must measure exactly 100 mm.', fontsize=8)
notes = ['Holder hole centres are 25 mm apart across the board and 95 mm along its length.',
         'The two layers occupy different depths. This sheet checks their footprints only.',
         'Electronics height is 25 mm. Coil height allowance is 19 mm and needs a physical check.',
         'The lid, strap contact, printed tolerances and acoustic output still need physical checks.']
for index, text in enumerate(notes):
    ax.text(15, 61 - 7 * index, text, fontsize=7.5)
fig.savefig(ROOT / 'paper-fit-check.pdf')
print('A4 template written at 210 × 297 mm.')
