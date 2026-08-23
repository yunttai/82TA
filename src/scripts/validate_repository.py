#!/usr/bin/env python3
"""Validate the Codex dual harness, canonical contracts, and src-only layout."""
from __future__ import annotations
import argparse, json, re, subprocess, sys, tomllib
from pathlib import Path
from typing import Any
import yaml
from _contract_utils import canonical_files, project_root

ROOT_ALLOWLIST={'.codex','.agents','.codegraph','_workspace','src','AGENTS.md','README.md','.gitignore','.git'}
REQUIRED={
 'AGENTS.md','.codex/config.toml',
 '.codex/agents/service-product-lead.toml','.codex/agents/routing-technical-lead.toml','.codex/agents/contract-steward.toml','.codex/agents/integration-qa.toml',
 '.agents/skills/service-product-orchestrator/SKILL.md','.agents/skills/routing-intelligence-orchestrator/SKILL.md',
 '.agents/skills/shared-context-loader/SKILL.md','.agents/skills/shared-contract-governance/SKILL.md',
 '.agents/skills/integration-coherence-qa/SKILL.md','.agents/skills/source-layout-guard/SKILL.md',
 'src/apps/web/AGENTS.md','src/services/service-api/AGENTS.md','src/services/routing-api/AGENTS.md',
 'src/packages/routing-domain/AGENTS.md','src/packages/provider-core/AGENTS.md','src/packages/bus-intelligence-core/AGENTS.md',
 'src/contracts/AGENTS.md','src/tests/AGENTS.md',
 'src/docs/shared/PRD.md','src/contracts/CONTEXT_MANIFEST.json','src/contracts/CONTRACT_LOCK.json',
 'src/contracts/harness/harness-registry.v1.yaml','src/contracts/openapi/service-public.v1.yaml',
 'src/contracts/openapi/routing-private.v1.yaml','src/contracts/database/service-db.dbml','src/contracts/database/routing-db.dbml',
 'src/docs/codex-prompts/PROMPT_INDEX.md','src/docs/codex-prompts/ALL_COPY_PASTE_PROMPTS.md',
}
ORCHESTRATOR_REQUIRED={'src/contracts/CONTEXT_MANIFEST.json','src/contracts/CONTRACT_LOCK.json','snapshot_context.py','shared-contract-governance','WORKPLAN.md','src/'}
CODE_EXT={'.py','.pyi','.js','.jsx','.ts','.tsx','.mjs','.cjs','.java','.kt','.go','.rs','.c','.cpp','.h','.hpp','.sql','.sh','.bash','.zsh','.ps1','.tf','.tfvars','.ipynb'}

def parse_fm(path:Path)->dict[str,Any]:
 text=path.read_text(encoding='utf-8'); m=re.match(r'^---\n(.*?)\n---\n',text,re.S)
 if not m: raise ValueError('missing YAML frontmatter')
 data=yaml.safe_load(m.group(1));
 if not isinstance(data,dict): raise ValueError('frontmatter must be object')
 for k in ('name','description'):
  if not isinstance(data.get(k),str) or not data[k].strip(): raise ValueError(f'{k} required')
 return data

def parse_agent(path:Path)->dict[str,Any]:
 data=tomllib.loads(path.read_text(encoding='utf-8'))
 for k in ('name','description','developer_instructions'):
  if not isinstance(data.get(k),str) or not data[k].strip(): raise ValueError(f'{k} required')
 return data

def errors(root:Path)->list[str]:
 out=[]
 for name in sorted({p.name for p in root.iterdir()}-ROOT_ALLOWLIST): out.append(f'root item violates src-only/Codex policy: {name}')
 for rel in sorted(REQUIRED):
  if not (root/rel).exists(): out.append(f'required file missing: {rel}')
 if (root/'.claude').exists() or (root/'CLAUDE.md').exists(): out.append('active legacy Claude control files remain')
 for base in (root/'.agents',root/'.codex'):
  if base.exists():
   for p in base.rglob('*'):
    if p.is_file() and p.suffix.lower() in CODE_EXT: out.append(f'executable file outside src: {p.relative_to(root)}')
 _,canon=canonical_files(root)
 for rel in canon:
  if not (root/rel).is_file(): out.append(f'canonical file missing: {rel}')
 try:
  cfg=tomllib.loads((root/'.codex/config.toml').read_text(encoding='utf-8')); ac=cfg.get('agents',{})
  if ac.get('enabled') is not True: out.append('.codex/config.toml must enable subagents')
  if int(ac.get('max_concurrent_threads_per_session',0))<2: out.append('Codex subagent concurrency must be >=2')
 except Exception as e: out.append(f'invalid .codex/config.toml: {e}')
 agent_names=set(); links={}
 for p in sorted((root/'.codex/agents').glob('*.toml')):
  try:
   d=parse_agent(p); name=d['name']; agent_names.add(name)
   if name!=p.stem: out.append(f'custom agent name/path mismatch: {p.relative_to(root)}')
   ins=d['developer_instructions']
   if 'src/' not in ins: out.append(f'custom agent lacks src-only rule: {name}')
   if 'AGENTS.md' not in ins: out.append(f'custom agent lacks AGENTS.md precedence: {name}')
   sec=ins.split('## 사용할 스킬',1)[1].split('\n## ',1)[0] if '## 사용할 스킬' in ins else ''
   links[name]=set(re.findall(r'`([a-z0-9-]+)`',sec))
  except Exception as e: out.append(f'invalid custom agent {p.relative_to(root)}: {e}')
 if not agent_names: out.append('no project custom agents found')
 skill_names=set()
 for p in sorted((root/'.agents/skills').glob('*/SKILL.md')):
  try:
   meta=parse_fm(p); name=meta['name']
   if name in skill_names: out.append(f'duplicate skill: {name}')
   skill_names.add(name)
   if name!=p.parent.name: out.append(f'skill name/path mismatch: {p.relative_to(root)}')
   if len(p.read_text(encoding='utf-8').splitlines())>500: out.append(f'SKILL.md >500 lines: {p.relative_to(root)}')
  except Exception as e: out.append(f'invalid skill {p.relative_to(root)}: {e}')
 for agent,ls in sorted(links.items()):
  for miss in sorted(ls-skill_names): out.append(f'custom agent {agent} references missing skill: {miss}')
 for workstream in (root/'src/docs/harnesses/service-product',root/'src/docs/harnesses/routing-intelligence'):
  for p in workstream.rglob('*'):
   if p.suffix.lower() in {'.yaml','.yml','.json','.dbml'}: out.append(f'duplicated machine contract in workstream: {p.relative_to(root)}')
 for name in ('service-product-orchestrator','routing-intelligence-orchestrator'):
  p=root/f'.agents/skills/{name}/SKILL.md'
  if not p.exists(): continue
  text=p.read_text(encoding='utf-8')
  for token in sorted(ORCHESTRATOR_REQUIRED):
   if token not in text: out.append(f'{name} misses context gate: {token}')
  for phrase in ('delegate','Wait for all','primary thread'):
   if phrase.lower() not in text.lower(): out.append(f'{name} misses Codex lifecycle phrase: {phrase}')
 for p in [root/'AGENTS.md',*sorted((root/'src').rglob('AGENTS.md'))]:
  if p.is_file() and p.stat().st_size>65536: out.append(f'AGENTS.md too large: {p.relative_to(root)}')
 return out

def syntax(root:Path)->list[str]:
 out=[]
 for p in sorted((root/'src').rglob('*.json')):
  try: json.loads(p.read_text(encoding='utf-8'))
  except Exception as e: out.append(f'invalid JSON {p.relative_to(root)}: {e}')
 for pat in ('*.yaml','*.yml'):
  for p in sorted((root/'src').rglob(pat)):
   try: yaml.safe_load(p.read_text(encoding='utf-8'))
   except Exception as e: out.append(f'invalid YAML {p.relative_to(root)}: {e}')
 for p in sorted((root/'.codex/agents').glob('*.toml')):
  try: tomllib.loads(p.read_text(encoding='utf-8'))
  except Exception as e: out.append(f'invalid TOML {p.relative_to(root)}: {e}')
 return out

def run(root,script,label):
 r=subprocess.run([sys.executable,str(root/'src/scripts'/script)],cwd=root,check=False)
 return None if r.returncode==0 else label

def main()->int:
 ap=argparse.ArgumentParser(); ap.add_argument('--layout-only',action='store_true'); ap.add_argument('--root',type=Path,default=None); a=ap.parse_args()
 root=a.root.resolve() if a.root else project_root(); out=errors(root)
 if not a.layout_only:
  out+=syntax(root)
  for s,l in [('validate_openapi.py','OpenAPI validation failed'),('validate_openapi_examples.py','OpenAPI examples failed'),('validate_harness_registry.py','Codex harness registry failed'),('validate_harness_evals.py','harness evals failed'),('verify_contract_lock.py','contract lock failed')]:
   x=run(root,s,l)
   if x: out.append(x)
 if out:
  print('REPOSITORY VALIDATION FAILED'); [print('-',x) for x in out]; return 1
 print('REPOSITORY VALIDATION OK'); return 0
if __name__=='__main__': raise SystemExit(main())
