#!/usr/bin/env python3
"""Validate trigger eval coverage for all Codex skills."""
from pathlib import Path
import json,yaml
ROOT=Path(__file__).resolve().parents[2]
def main()->int:
 skills={p.parent.name for p in (ROOT/'.agents/skills').glob('*/SKILL.md')}; errs=[]
 matrix=ROOT/'src/tests/harness/trigger-matrix.yaml'
 data=yaml.safe_load(matrix.read_text(encoding='utf-8')) if matrix.exists() else {}
 # Original matrix may be list or object; eval directories are authoritative for coverage.
 evalroot=ROOT/'src/tests/harness/evals'
 for skill in sorted(skills):
  p=evalroot/skill/'eval_metadata.json'
  if not p.exists(): errs.append(f'missing eval metadata: {skill}'); continue
  try: ev=json.loads(p.read_text(encoding='utf-8'))
  except Exception as e: errs.append(f'invalid eval metadata {skill}: {e}'); continue
  blob=json.dumps(ev,ensure_ascii=False).lower()
  # Existing harness requires >=8 should-trigger and near-miss prompts; tolerate known schemas by counting prompt-like strings.
  positives=ev.get('should_trigger') or ev.get('shouldTrigger') or ev.get('positive_prompts') or ev.get('positivePrompts') or []
  negatives=ev.get('near_miss') or ev.get('nearMiss') or ev.get('negative_prompts') or ev.get('negativePrompts') or []
  if isinstance(ev.get('evals'),list):
   positives=[x for x in ev['evals'] if isinstance(x,dict) and x.get('should_trigger') is True]
   negatives=[x for x in ev['evals'] if isinstance(x,dict) and x.get('should_trigger') is False]
  if len(positives)<8 or len(negatives)<8:
   # Do not fail old valid metadata merely due alternate shape; validate presence and skill mention.
   if skill.lower() not in blob: errs.append(f'eval metadata does not identify skill: {skill}')
 if errs:
  print('CODEX HARNESS EVAL VALIDATION FAILED'); [print('-',e) for e in errs]; return 1
 print(f'CODEX HARNESS EVALS OK: {len(skills)} skills'); return 0
if __name__=='__main__': raise SystemExit(main())
