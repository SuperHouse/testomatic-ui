from pathlib import Path

_git_head = Path(__file__).parent / '.git' / 'HEAD'


def _branch_suffix():
    try:
        content = _git_head.read_text().strip()
        if content.startswith('ref: refs/heads/'):
            branch = content[len('ref: refs/heads/'):]
            if branch != 'main':
                return f'-{branch}'
    except OSError:
        pass
    return ''


VERSION = '2026.08.31.1' + _branch_suffix()
