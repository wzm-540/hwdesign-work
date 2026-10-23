"""Create a clean source/evidence archive for transfer to the student's GitHub.

This is NOT the Gradescope ZIP, which must be downloaded from LLM grader.
"""
import hashlib
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parent


def files():
    for p in sorted(ROOT.iterdir()):
        if p.is_file() and (p.suffix in {'.py','.cpp','.hpp','.tcl','.md'} or p.name=='.gitignore'):
            yield p
    for subdir in ['vectors','evidence']:
        yield from sorted(p for p in (ROOT/subdir).rglob('*') if p.is_file())


def main():
    assert (ROOT/'results.md').exists()
    manifest=ROOT/'evidence/source_manifest.txt'
    manifest.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+str(p.relative_to(ROOT))+'\n'
                               for p in files() if p!=manifest))
    output=ROOT.parent/'takehome_submission.zip'
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for p in files():
            archive.write(p,Path('cmdresp/takehome')/p.relative_to(ROOT))
    print(output)
    print(f'{output.stat().st_size} bytes; contains code, prompt, results, vectors and cited evidence')


if __name__=='__main__':
    main()
