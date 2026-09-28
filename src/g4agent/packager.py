"""Build submission.zip from the project sources.

Steps:
1. Stage the submission sources (plus an optional variant overlay from variants/<name>/) into a temp dir.
2. Compute the closure: only files reachable from agent.yaml (includes, sub-agents, skills, adapters)
   and eval_config.yaml are shipped.
3. Mirror each skill's references/ into resources/ (the layout the competition overview shows; stock ADK
   reads references/, so shipping both is safe either way).
4. Validate the build directory strictly, write a deterministic zip, then re-validate the zip itself.

Usage:
    python -m g4agent.packager [--variant NAME] [--out submission/submission.zip] [--compile]
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from .loader import SubmissionError, closure, load_agent_tree
from .validator import validate_dir, validate_zip

PROJECT = Path(__file__).resolve().parents[2]
SOURCE_ENTRIES = ("agent.yaml", "eval_config.yaml", "configs", "prompts", "sub_agents", "skills", "adapters")
_ZIP_DATE = (2026, 1, 1, 0, 0, 0)  # fixed timestamp for byte-reproducible archives


def _ignore(_dir: str, names: list[str]) -> list[str]:
    return [n for n in names if n.startswith(".") or n == "__pycache__" or n.endswith(".pyc")]


def stage(variant: str | None, dest: Path) -> None:
    for entry in SOURCE_ENTRIES:
        src = PROJECT / entry
        if src.is_dir():
            shutil.copytree(src, dest / entry, ignore=_ignore, dirs_exist_ok=True)
        elif src.is_file():
            shutil.copy2(src, dest / entry)
    if variant:
        vdir = PROJECT / "variants" / variant
        if not vdir.is_dir():
            raise SubmissionError(f"unknown variant: {variant} (see variants/)")
        shutil.copytree(vdir, dest, ignore=_ignore, dirs_exist_ok=True)


def build_tree(staging: Path, build: Path) -> list[Path]:
    tree = load_agent_tree(staging)
    files = sorted(closure(tree))
    staging = staging.resolve()
    for f in files:
        rel = f.relative_to(staging)
        (build / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, build / rel)
    for skill_dir in tree.skill_dirs:
        refs = build / skill_dir.relative_to(staging) / "references"
        if refs.is_dir():
            shutil.copytree(refs, refs.parent / "resources", dirs_exist_ok=True)
    return files


def write_zip(build: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(build.rglob("*")):
            if p.is_file():
                info = zipfile.ZipInfo(p.relative_to(build).as_posix(), date_time=_ZIP_DATE)
                info.external_attr = 0o644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, p.read_bytes())


def package(variant: str | None, out: Path, *, compile_adk: bool, keep_build: Path | None = None) -> int:
    with tempfile.TemporaryDirectory() as td:
        staging, build = Path(td) / "staging", Path(td) / "build"
        staging.mkdir()
        build.mkdir()
        print(f"[1/5] staging sources{f' + variant {variant}' if variant else ''}")
        stage(variant, staging)
        print("[2/5] computing closure and building submission tree")
        try:
            files = build_tree(staging, build)
        except SubmissionError as exc:
            print(f"ERROR: {exc}")
            return 1
        print(f"      {len(files)} reachable files")
        print("[3/5] validating build tree")
        report = validate_dir(build, strict_tree=True, compile_adk=compile_adk)
        print(report.render())
        if not report.ok:
            return 1
        print(f"[4/5] writing {out}")
        write_zip(build, out)
        if keep_build:
            shutil.rmtree(keep_build, ignore_errors=True)
            shutil.copytree(build, keep_build)
    print("[5/5] re-validating the archive")
    zreport = validate_zip(out, compile_adk=False)
    if not zreport.ok:
        print(zreport.render())
        return 1
    with zipfile.ZipFile(out) as zf:
        names = sorted(zf.namelist())
    digest = hashlib.sha256(out.read_bytes()).hexdigest()[:16]
    print("\nARCHIVE CONTENTS:")
    for n in names:
        print(f"  {n}")
    print(f"\nagent.yaml at root: {'agent.yaml' in names}")
    print(f"archive: {out}")
    print(f"size: {out.stat().st_size / 1024:.1f} KiB  sha256[:16]={digest}")
    print("VALIDATION: PASSED")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default=None, help="overlay variants/<name>/ on the sources")
    ap.add_argument("--out", type=Path, default=PROJECT / "submission" / "submission.zip")
    ap.add_argument("--compile", action="store_true", help="also compile the tree with google-adk")
    ap.add_argument("--keep-build", type=Path, default=None, help="copy the unzipped build here")
    args = ap.parse_args(argv)
    return package(args.variant, args.out.resolve(), compile_adk=args.compile, keep_build=args.keep_build)


if __name__ == "__main__":
    sys.exit(main())
