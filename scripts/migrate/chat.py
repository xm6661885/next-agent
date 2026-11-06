"""Move defaults.title_model into titles.model, preserving TOML formatting."""
import argparse
from pathlib import Path
import tomlkit


def migrate(data, dry_run=False):
    path = data / 'config' / 'chat.toml'
    if not path.exists(): return
    doc = tomlkit.parse(path.read_text())
    defaults = doc.get('defaults', {})
    if 'title_model' not in defaults: return
    titles = doc.setdefault('titles', tomlkit.table())
    if 'model' in titles and titles['model']!=defaults['title_model']:
        raise ValueError('Conflicting defaults.title_model and titles.model; resolve before migration')
    print(f'{path}: move defaults.title_model to titles.model')
    if dry_run: return
    titles['model'] = defaults['title_model']
    del defaults['title_model']
    path.write_text(tomlkit.dumps(doc))


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path(__file__).resolve().parents[2] / 'data')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    migrate(args.data, args.dry_run)
