#!/usr/bin/python3
"""Offline drift check for the agent docs: relative links, #anchors, backticked repo paths, and
script subcommands/flags quoted in backticks must exist. Exits 1 with one line per problem."""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINKED = ['CLAUDE.md', 'README.md', 'prep-notes.md']  # links and anchors checked
STRICT = ['CLAUDE.md']                                # backticked paths checked too
SCRIPTS = {'gm.py': ['./gm.py'], 'trade.py': ['./trade.py'], 'draft.py': ['./draft.py'],
           'rebuild_board.py': ['python3', 'rebuild_board.py']}


def doc_files():
    out = LINKED[:]
    for d in ('.claude/commands', '.claude/agents'):
        out += sorted(os.path.join(d, f) for f in os.listdir(os.path.join(ROOT, d)) if f.endswith('.md'))
    return out


def slug(heading):
    return re.sub(r'[^\w\- ]', '', heading.strip().lower()).replace(' ', '-')


def anchors(text):
    return {slug(m) for m in re.findall(r'^#+ (.+)$', text, re.M)}


def skip_private(path):
    # CI and public clones have no private/ checkout.
    return path.startswith('private/') and not os.path.isdir(os.path.join(ROOT, 'private'))


def check_links(name, text, exists, read):
    errs = []
    for target in re.findall(r'\]\(([^)\s]+)\)', text):
        if re.match(r'[a-z]+:', target):
            continue
        path, _, frag = target.partition('#')
        rel = os.path.normpath(os.path.join(os.path.dirname(name), path)) if path else name
        if skip_private(rel):
            continue
        if not exists(rel):
            errs.append('%s: broken link %s' % (name, target))
        elif frag and rel.endswith('.md') and frag not in anchors(read(rel)):
            errs.append('%s: missing anchor %s' % (name, target))
    return errs


def check_paths(name, text, exists):
    errs = []
    for span in re.findall(r'`([^`\s]+)`', text):
        span = span[2:] if span.startswith('./') else span
        if not re.match(r'[\w.][\w.\-/]*$', span) or not re.search(r'(/|\.(md|py|csv|txt|json|sh))$', span):
            continue
        if not skip_private(span) and not exists(span):
            errs.append('%s: missing path `%s`' % (name, span))
    return errs


def check_commands(name, text, helptext):
    """Every `./gm.py <sub> --flag` (and the other scripts' flags) in a code span must be in --help."""
    errs = []
    for span in re.findall(r'`([^`\n]+)`', text):
        for script in SCRIPTS:
            m = re.search(r'(?:\./|python3 )%s\b(.*)' % re.escape(script), span)
            if not m:
                continue
            args = m.group(1)
            subs = re.findall(r'\{([\w,]+)\}', helptext(script, None))
            subs = subs[0].split(',') if subs else []
            sub = next((w for w in args.split() if w in subs), None)
            known = helptext(script, None) + (helptext(script, sub) if sub else '')
            for flag in re.findall(r'(?<![\w-])(--[a-z][\w-]*)', args):
                if flag not in re.findall(r'--[a-z][\w-]*', known):
                    errs.append('%s: `%s` has no %s' % (name, span, flag))
    return errs


_help = {}


def real_help(script, sub):
    key = (script, sub)
    if key not in _help:
        cmd = [sys.executable, os.path.join(ROOT, script)] + ([sub] if sub else []) + ['--help']
        _help[key] = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    universal_newlines=True, cwd=ROOT).stdout
    return _help[key]


def selftest():
    docs = {'a.md': '# Lock-In & roster\n', 'b.md': ''}
    ex, rd = docs.__contains__, docs.get
    assert check_links('b.md', '[x](a.md#lock-in--roster)', ex, rd) == []
    assert check_links('b.md', '[x](a.md#gone) [y](c.md) [z](https://e.com)', ex, rd) == [
        'b.md: missing anchor a.md#gone', 'b.md: broken link c.md']
    assert check_paths('b.md', '`a.md` `./a.md` `.c/d.py` `<x>/y.md` `--flag` `V/wk`', ex) == [
        'b.md: missing path `.c/d.py`']
    fake = lambda s, sub: 'positional {lock,week}\n --date' + (' --commit' if sub == 'lock' else '')
    assert check_commands('b.md', '`./gm.py --date D lock "P" 5 --commit` `./gm.py week --commit`', fake) == [
        'b.md: `./gm.py week --commit` has no --commit']


def main():
    selftest()
    exists = lambda p: os.path.exists(os.path.join(ROOT, p))
    read = lambda p: open(os.path.join(ROOT, p), encoding='utf-8').read()
    errs = []
    for name in doc_files():
        text = read(name)
        errs += check_commands(name, text, real_help)
        if name in LINKED or name.startswith('.claude/'):
            errs += check_links(name, text, exists, read)
        if name in STRICT or name.startswith('.claude/'):
            errs += check_paths(name, text, exists)
    for e in errs:
        print(e)
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main())
