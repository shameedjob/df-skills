"""Validate, summarise, review, and gate an es-factory plan.json.

  python plan_review.py validate PLAN       # schema errors, exit 1 if any
  python plan_review.py summary PLAN        # readable checklist for the operator
  python plan_review.py review PLAN [--all] # step through and accept / rework / edit steps
  python plan_review.py gate PLAN           # exit 1 unless valid and every step accepted
"""
import argparse
import json
import os
import sys

LAYERS = {'frontend': 'designer', 'backend': 'programmer'}
EFFORTS = ('low', 'medium', 'high')


def load_plan(file: str):
    with open(file, 'r', encoding='utf-8') as f:
        return json.load(f)


def validate(plan) -> list:
    errors = []
    if not isinstance(plan, dict):
        return ['plan must be a JSON object']
    if not str(plan.get('description', '')).strip():
        errors.append('plan: missing description')
    sections = plan.get('sections')
    if not isinstance(sections, list) or not sections:
        return errors + ['plan: sections must be a non-empty list']

    seen_ids = set()
    for s_idx, section in enumerate(sections, 1):
        where = f'section {s_idx}'
        for key in ('title', 'test_instructions'):
            if not str(section.get(key, '')).strip():
                errors.append(f'{where}: missing {key}')
        steps = section.get('steps')
        if not isinstance(steps, list) or not steps:
            errors.append(f'{where}: steps must be a non-empty list')
            continue
        for step in steps:
            step_id = step.get('id')
            where = f'step {step_id}' if step_id else f'section {s_idx}, step without id'
            if not step_id:
                errors.append(f'{where}: missing id')
            elif step_id in seen_ids:
                errors.append(f'{where}: duplicate id')
            else:
                seen_ids.add(step_id)
            if not str(step.get('description', '')).strip():
                errors.append(f'{where}: missing description')
            layer = step.get('layer')
            if layer not in LAYERS:
                errors.append(f'{where}: layer must be one of {sorted(LAYERS)}')
            elif step.get('subagent') != LAYERS[layer]:
                errors.append(f'{where}: {layer} steps use subagent "{LAYERS[layer]}"')
            if step.get('effort') not in EFFORTS:
                errors.append(f'{where}: effort must be one of {list(EFFORTS)}')
            files = step.get('files')
            if not isinstance(files, list) or not files:
                errors.append(f'{where}: files must be a non-empty list')
            if not isinstance(step.get('accepted'), bool):
                errors.append(f'{where}: accepted must be true or false')
            if 'feedback' in step and not isinstance(step['feedback'], str):
                errors.append(f'{where}: feedback must be a string')
    return errors


def iter_steps(plan):
    for section in plan['sections']:
        for step in section['steps']:
            yield section, step


def summary(plan) -> str:
    lines = [plan['description'], '']
    for s_idx, section in enumerate(plan['sections'], 1):
        lines.append(f'Section {s_idx}: {section["title"]}')
        for step in section['steps']:
            mark = 'x' if step.get('accepted') else ' '
            lines.append(f'  [{mark}] {step["id"]} ({step["layer"]}/{step["subagent"]}, '
                         f'{step["effort"]}) {step["description"]}')
            for path in step['files']:
                lines.append(f'        - {path}')
            if step.get('feedback'):
                lines.append(f'        rework: {step["feedback"]}')
        lines.append(f'  Test: {section["test_instructions"]}')
        lines.append('')
    return '\n'.join(lines).rstrip()


def save_plan(plan, file: str):
    tmp = file + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(plan, f, indent=2)
        f.write('\n')
    os.replace(tmp, file)


def show_step(section, step, position: str):
    status = 'ACCEPTED' if step['accepted'] else ('REWORK' if step.get('feedback') else 'pending')
    print(f'\n=== {position}  Section: {section["title"]} ===')
    print(f'Step {step["id"]} [{status}]  {step["layer"]}/{step["subagent"]}, effort {step["effort"]}')
    print(f'  {step["description"]}')
    for path in step['files']:
        print(f'  - {path}')
    if step.get('feedback'):
        print(f'  rework note: {step["feedback"]}')


def choose(prompt: str, options) -> str:
    while True:
        answer = input(f'{prompt} [{"/".join(options)}]: ').strip().lower()
        if answer in options:
            return answer
        print(f'  choose one of: {", ".join(options)}')


def edit_step(step):
    field = choose('Edit (d)escription, (l)ayer, (e)ffort, (f)iles, (c)ancel', ('d', 'l', 'e', 'f', 'c'))
    if field == 'd':
        text = input('New description (blank keeps current): ').strip()
        if text:
            step['description'] = text
    elif field == 'l':
        layer = {'f': 'frontend', 'b': 'backend'}[choose('Layer (f)rontend / (b)ackend', ('f', 'b'))]
        step['layer'], step['subagent'] = layer, LAYERS[layer]
    elif field == 'e':
        step['effort'] = {'l': 'low', 'm': 'medium', 'h': 'high'}[choose('Effort (l)ow / (m)edium / (h)igh', ('l', 'm', 'h'))]
    elif field == 'f':
        print('Enter one path per line (prefix new files with "NEW: "); blank line to finish, blank first line keeps current.')
        files = []
        while path := input('  > ').strip():
            files.append(path)
        if files:
            step['files'] = files
    return field != 'c'


def review(plan, file: str, include_all: bool):
    steps = [(s, st) for s, st in iter_steps(plan) if include_all or not st['accepted']]
    if not steps:
        print('Every step is already accepted (use --all to review them anyway).')
        return
    print('(a)ccept  (r)ework with a note  (e)dit fields  (n)ext  (b)ack  (q)uit')
    i = 0
    while 0 <= i < len(steps):
        section, step = steps[i]
        show_step(section, step, f'{i + 1}/{len(steps)}')
        action = choose('Action', ('a', 'r', 'e', 'n', 'b', 'q'))
        if action == 'a':
            step['accepted'] = True
            step.pop('feedback', None)
            i += 1
        elif action == 'r':
            note = input('What needs reworking? ').strip()
            if not note:
                print('  no note given; step unchanged')
                continue
            step['accepted'] = False
            step['feedback'] = note
            i += 1
        elif action == 'e':
            if edit_step(step):
                step['accepted'] = False
                errors = validate(plan)
                if errors:
                    print('\n'.join(f'  warning: {e}' for e in errors))
        elif action == 'n':
            i += 1
        elif action == 'b':
            i = max(i - 1, 0)
        else:
            break
        if action in ('a', 'r', 'e'):
            save_plan(plan, file)

    pending = [st['id'] for _, st in iter_steps(plan) if not st['accepted']]
    rework = [st['id'] for _, st in iter_steps(plan) if st.get('feedback')]
    print(f'\nSaved {file}.')
    if not pending:
        print('All steps accepted: the plan passes the gate.')
    else:
        print(f'Not accepted: {", ".join(pending)}')
        if rework:
            print(f'Marked for rework: {", ".join(rework)} (tell the orchestrator to revise the plan)')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('validate', 'summary', 'review', 'gate'))
    parser.add_argument('plan')
    parser.add_argument('--all', action='store_true', help='review: include already accepted steps')
    args = parser.parse_args()

    try:
        plan = load_plan(args.plan)
    except (OSError, json.JSONDecodeError) as e:
        print(f'error: cannot read plan: {e}')
        sys.exit(1)

    errors = validate(plan)
    if errors:
        for error in errors:
            print(f'error: {error}')
        sys.exit(1)

    if args.command == 'validate':
        print('plan is valid')
    elif args.command == 'summary':
        print(summary(plan))
    elif args.command == 'review':
        try:
            review(plan, args.plan, args.all)
        except (KeyboardInterrupt, EOFError):
            print('\nStopped; changes made so far are saved.')
    else:
        pending = [step['id'] for _, step in iter_steps(plan) if not step['accepted']]
        if pending:
            print(f'error: steps not accepted: {", ".join(pending)}')
            sys.exit(1)
        print('all steps accepted')


if __name__ == '__main__':
    main()
