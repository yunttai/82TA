#!/usr/bin/env python3
"""Validate Codex dual harness registry, custom agents, skills, scopes and ledgers."""
from __future__ import annotations
import tomllib
from pathlib import Path
from typing import Any
import yaml
ROOT=Path(__file__).resolve().parents[2]
REG=ROOT/'src/contracts/harness/harness-registry.v1.yaml'
def exists(x:str)->bool: return (ROOT/x).exists()
def agent_name(p:Path)->str: return str(tomllib.loads(p.read_text(encoding='utf-8')).get('name',''))
def main()->int:
 data=yaml.safe_load(REG.read_text(encoding='utf-8')); errs=[]
 if data.get('runtime')!='codex': errs.append('registry.runtime must be codex')
 for key in ('root','projectConfig','customAgents','skills','prompts'):
  val=data.get('instructionFiles',{}).get(key)
  if not isinstance(val,str) or not exists(val): errs.append(f'instructionFiles.{key} invalid: {val}')
 for key in ('manifest','lock','sharedDocs','contracts'):
  val=data.get('canonicalContext',{}).get(key)
  if not isinstance(val,str) or not exists(val): errs.append(f'canonicalContext.{key} invalid: {val}')
 hs=data.get('harnesses',{})
 if set(hs)!={'service-product','routing-intelligence'}: errs.append('must define exactly two harnesses')
 all_agents=set(); all_skills=set()
 for hname,h in hs.items():
  op=h.get('orchestrator'); text=''
  if not isinstance(op,str) or not exists(op): errs.append(f'{hname}: orchestrator invalid: {op}')
  else: text=(ROOT/op).read_text(encoding='utf-8')
  ws=h.get('workspace')
  if not isinstance(ws,str) or not exists(ws): errs.append(f'{hname}: workspace invalid')
  else:
   for ledger in ('WORKPLAN.md','STATUS.md','HANDOFF.md'):
    if not exists(f'{ws}/{ledger}'): errs.append(f'{hname}: missing {ledger}')
  for scope in h.get('finalWriteScopes',[]):
   if not isinstance(scope,str) or not scope.startswith('src/'): errs.append(f'{hname}: non-src scope {scope}')
  overlap=set(h.get('finalWriteScopes',[])) & set(h.get('deniedScopes',[]))
  if overlap: errs.append(f'{hname}: scope overlap {sorted(overlap)}')
  for agent in h.get('agents',[])+h.get('sharedAgents',[]):
   all_agents.add(agent); p=ROOT/f'.codex/agents/{agent}.toml'
   if not p.exists(): errs.append(f'{hname}: missing custom agent {agent}')
   elif agent_name(p)!=agent: errs.append(f'{hname}: agent name mismatch {agent}')
   if text and agent not in text: errs.append(f'{hname}: agent absent from orchestrator: {agent}')
  for skill in h.get('primarySkills',[]):
   all_skills.add(skill)
   if not exists(f'.agents/skills/{skill}/SKILL.md'): errs.append(f'{hname}: missing skill {skill}')
 for skill in data.get('sharedSkills',[]):
  all_skills.add(skill)
  if not exists(f'.agents/skills/{skill}/SKILL.md'): errs.append(f'missing shared skill {skill}')
 actual={agent_name(p) for p in (ROOT/'.codex/agents').glob('*.toml')}
 unmanaged=actual-all_agents
 if unmanaged: errs.append(f'unregistered agents: {sorted(unmanaged)}')
 if errs:
  print('HARNESS REGISTRY VALIDATION FAILED'); [print('-',e) for e in errs]; return 1
 print(f'CODEX HARNESS REGISTRY OK: {len(hs)} harnesses, {len(all_agents)} agents, {len(all_skills)} registered skills'); return 0
if __name__=='__main__': raise SystemExit(main())
