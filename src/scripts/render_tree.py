#!/usr/bin/env python3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SKIP={'.git','node_modules','__pycache__'}
def walk(p:Path,prefix=''):
 items=[x for x in sorted(p.iterdir(),key=lambda x:(not x.is_dir(),x.name.lower())) if x.name not in SKIP]
 for i,x in enumerate(items):
  last=i==len(items)-1; print(prefix+('└── ' if last else '├── ')+x.name)
  if x.is_dir(): walk(x,prefix+('    ' if last else '│   '))
print(ROOT.name); walk(ROOT)
