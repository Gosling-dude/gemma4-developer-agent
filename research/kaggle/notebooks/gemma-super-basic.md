# Gemma | Super Basic
source: https://www.kaggle.com/code/twangygarlic449/gemma-super-basic  votes=4 bestPublicScore=0.08 gpu=None runtime_s=19

# Gemma agent submission

This notebook creates a minimal declarative agent bundle and packages it as `submission.zip`.

Edit the values and `SYSTEM_PROMPT` below, then run the cells from top to bottom. The competition data is only used to inspect `tasks.jsonl`; the finished agent is evaluated by the competition harness.


```python
import json
import os
import shutil
import zipfile
from pathlib import Path

# Edit these values when changing the submission.
MODEL = 'gemma-4-31b-it-qat-w4a16-ct'
SAMPLING = {
    'temperature': 0.2,
    'top_p': 0.95,
    'top_k': 40,
    'max_output_tokens': 8192,
    'thinking_budget': 4096,
}
TOOLS = [
    'run_command',
    'read_file',
    'edit_file',
    'get_status',
    'submit_patch',
]

WORK_DIR = Path('/kaggle/working') if Path('/kaggle/working').exists() else Path.cwd()
BUNDLE_DIR = WORK_DIR / 'submission_bundle'
ZIP_PATH = WORK_DIR / 'submission.zip'

```

```python
def find_data_dir():
    candidates = []
    if os.environ.get('GEMMA_AGENT_DATA'):
        candidates.append(Path(os.environ['GEMMA_AGENT_DATA']))
    candidates.extend([
        Path('/kaggle/input/competitions/gemma-4-developer-agent'),
        Path('/kaggle/input/gemma-4-developer-agent'),
        Path('competition_data'),
    ])
    return next((path for path in candidates if (path / 'tasks.jsonl').exists()), None)


DATA_DIR = find_data_dir()
if DATA_DIR is None:
    TASKS = []
    print('tasks.jsonl not found; skipping task inspection.')
else:
    with (DATA_DIR / 'tasks.jsonl').open(encoding='utf-8') as file:
        TASKS = [json.loads(line) for line in file if line.strip()]
    print(f'Loaded {len(TASKS)} tasks from {DATA_DIR}.')
    if TASKS:
        print('Fields:', ', '.join(TASKS[0].keys()))
        print('First issue:')
        print(TASKS[0].get('problem_statement', '')[:1000])

```
```
[output] Loaded 129 tasks from /kaggle/input/competitions/gemma-4-developer-agent.
Fields: instance_id, repo, base_commit, patch, test_patch, problem_statement, hints_text, created_at
First issue:
👷 Automate release preparation

## Pull Request

👷 Automate release preparation

<!--
Please start with a GitHub Discussion.

Once a team member asks you to open a PR, create it and link the discussion here.

Obvious typo fixes can be made in a PR without starting a discussion.
-->

Discussion: <!-- Link to the GitHub Discussion -->

## Description

<!-- Write the description of your PR here -->

## AI Disclaimer

Codex with GPT-5.5, based on https://github.com/fastapi/asyncer/pull/608, reviewed by hand.

<!-- If using AI, write here the prompt and model used -->

<details>
<summary>AI transcript</summary>

<!-- Paste here the entire AI transcript -->

</details>

## Checklist

- [ ] This PR is an obvious typo fix, or it links to a GitHub Discussion for the proposed code change.
- [ ] I added tests for the change.
- [ ] The new or updated tests fail on the main branch and pass on this PR.
- [ ] Coverage stays at 100%.
- [ ] The documentation explain

```

```python
SYSTEM_PROMPT = '''
You are an autonomous software engineer working in the repository at /workspace.

Goal: fix the issue in the user message with the smallest correct patch, then call submit_patch.

Rules:
- Inspect the repository before editing.
- Do not modify tests, pytest.ini, conftest.py, CI, or packaging files.
- Do not install packages; the environment is offline and dependencies are already available.
- Use read_file to inspect code and run_command for searches and focused checks.
- Use edit_file with an exact, unique old_string and preserve indentation.
- Do not leave scratch files in /workspace.
- Call submit_patch when the fix is complete.

Workflow:
1. Extract the expected and actual behavior from the issue.
2. Search for the relevant symbols, error messages, and files.
3. Read the relevant code and make a minimal root-cause fix.
4. Run a focused check or test for the change.
5. Inspect git diff, remove unintended changes, and call submit_patch.
''' 

```

```python
def write_file(relative_path, text):
    path = BUNDLE_DIR / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + os.linesep, encoding='utf-8')


shutil.rmtree(BUNDLE_DIR, ignore_errors=True)
BUNDLE_DIR.mkdir(parents=True)

sampling_yaml = os.linesep.join([
    'temperature: ' + str(SAMPLING['temperature']),
    'top_p: ' + str(SAMPLING['top_p']),
    'top_k: ' + str(SAMPLING['top_k']),
    'max_output_tokens: ' + str(SAMPLING['max_output_tokens']),
    'thinking_config:',
    '  thinking_budget: ' + str(SAMPLING['thinking_budget']),
    '  include_thoughts: false',
])
tools_yaml = os.linesep.join('  - ' + tool for tool in TOOLS)
agent_yaml = os.linesep.join([
    'name: swe_agent',
    'model: ' + MODEL,
    'description: Fixes repository issues with a small, verified patch.',
    'instruction: !include prompts/system.md',
    'generate_content_config: !include configs/sampling.yaml',
    'tools:',
    tools_yaml,
])

write_file('prompts/system.md', SYSTEM_PROMPT)
write_file('configs/sampling.yaml', sampling_yaml)
write_file('agent.yaml', agent_yaml)
print(f'Wrote bundle to {BUNDLE_DIR}')

```
```
[output] Wrote bundle to /kaggle/working/submission_bundle

```

```python
def package(bundle_dir, zip_path):
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle_dir.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(bundle_dir).as_posix())
    return zip_path


required_files = [
    BUNDLE_DIR / 'agent.yaml',
    BUNDLE_DIR / 'prompts' / 'system.md',
    BUNDLE_DIR / 'configs' / 'sampling.yaml',
]
missing = [path for path in required_files if not path.exists()]
if missing:
    raise FileNotFoundError('Missing bundle files: ' + ', '.join(str(path) for path in missing))

ZIP_PATH = package(BUNDLE_DIR, ZIP_PATH)
with zipfile.ZipFile(ZIP_PATH) as archive:
    names = archive.namelist()
if 'agent.yaml' not in names:
    raise ValueError('agent.yaml is missing from the archive.')

print(f'Created {ZIP_PATH}')
print(os.linesep.join(names))

```
```
[output] Created /kaggle/working/submission.zip
agent.yaml
configs/sampling.yaml
prompts/system.md

```

## Next steps

Edit `SYSTEM_PROMPT`, `TOOLS`, or `SAMPLING` to develop the agent. The notebook intentionally stops at the smallest useful scaffold: task inspection, prompt definition, bundle creation, and packaging.

