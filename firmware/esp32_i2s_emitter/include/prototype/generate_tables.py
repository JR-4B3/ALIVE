import math
from pathlib import Path
sin=math.sin; pi=math.pi
arrays=[]
for direction in (1,2,3):
 for outro in ((False,True) if direction==2 else (False,)):
  rate=16000 if direction==2 else 4000
  values=[]
  for frame in range(int(rate*1.8)):
   t=frame/rate; envelope=sin(pi*frame/(rate*1.8))
   if direction==1: value=.85*sin(2*pi*173*t+.15*sin(2*pi*.7*t))
   elif direction==2: value=.65*max(0,sin(2*pi*(2.7 if outro else 1.7)*t))**8*sin(2*pi*(3600*t+(-1 if outro else 1)*330*t*t))
   else: value=.32*sin(2*pi*181*t+1.2*sin(2*pi*.4*t))+.32*sin(2*pi*187*t)+.25*sin(2*pi*307*t+1.8*sin(2*pi*.6*t))
   values.append(int(1200*envelope**2*value))
  values.append(0)
  name=f'sound{direction}{"outro" if outro else ""}'
  lines=[','.join(map(str,values[i:i+32])) for i in range(0,len(values),32)]
  arrays.append(f'static const int16_t {name}[] = {{\n'+',\n'.join(lines)+'\n};')
Path(__file__).with_name('space_tables.h').write_text('// Generated PCM tables for the throwaway sound study.\n'+ '\n'.join(arrays)+'\n')
