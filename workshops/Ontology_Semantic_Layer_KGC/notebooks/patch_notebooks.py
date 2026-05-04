#!/usr/bin/env python3
"""Patch notebook files to inject the Ontop endpoint URL."""
import json, glob, sys

endpoint = sys.argv[1]
nb_dir = sys.argv[2]

for f in glob.glob(nb_dir + '/*.ipynb'):
    with open(f) as fh:
        nb = json.load(fh)
    changed = False
    for c in nb['cells']:
        if c['cell_type'] != 'code':
            continue
        new = [l.replace('ONTOP_ENDPOINT = ""', 'ONTOP_ENDPOINT = "' + endpoint + '"') for l in c['source']]
        if new != c['source']:
            c['source'] = new
            changed = True
    if changed:
        with open(f, 'w') as fh:
            json.dump(nb, fh, indent=1)
        print(f"  Patched: {f}")
