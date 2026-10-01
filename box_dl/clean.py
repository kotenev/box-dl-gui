"""Remove full-page watermark-background images from PDFs.

Box preview PDFs (and similar scans) often bake a repeating watermark pattern
into one full-page raster image placed *behind* the real content. This module
finds such images -- large raster XObjects covering ~all of a page -- and
deletes them, keeping vector text, drawings and small figures intact.

Detection heuristic (per page, all must hold):

- the image covers ``min_coverage`` (default 0.85) of the page area;
- the stored raster is at least ``min_dimension_px`` (default 400) on a side,
  so small logos/stamps/figures are never touched;
- optional ``max_pages_share`` guard (default 1.0 = off): an image reused on
  more than that share of pages is treated as template chrome (header/footer
  background) rather than a watermark -- pass e.g. ``0.9`` to protect it.

Removal uses ``Page.delete_image(xref)`` (replaces the XObject with a tiny
transparent image) followed by ``save(garbage=4, deflate=True)`` so the
orphaned stream is dropped. Use :func:`clean_file` for files,
:func:`clean_bytes` for in-memory data, or the ``box-dl-clean`` CLI.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

log = logging.getLogger(__name__)


@dataclass
class CleanResult:
    """Outcome of one :func:`clean_file` / :func:`clean_bytes` call."""

    pages_total: int = 0
    pages_cleaned: int = 0
    removed_xrefs: List[int] = field(default_factory=list)
    bytes_before: int = 0
    bytes_after: int = 0


def find_background_images(page, min_coverage: float = 0.85,
                           min_dimension_px: int = 400) -> List[int]:
    """Return xrefs of full-page background images placed on ``page``."""
    area = page.rect.width * page.rect.height
    if area <= 0:
        return []
    found: List[int] = []
    for img in page.get_images(full=True):
        xref = img[0]
        width_px, height_px = img[2], img[3]
        if min(width_px, height_px) < min_dimension_px:
            continue
        try:
            rects = page.get_image_rects(xref)
        except ValueError:  # stale xref -- treat as absent
            continue
        if any(r.width * r.height / area >= min_coverage for r in rects):
            found.append(xref)
    return found


def clean_doc(doc, min_coverage: float = 0.85, min_dimension_px: int = 400,
              max_pages_share: float = 1.0) -> CleanResult:
    """Delete watermark backgrounds in an open ``pymupdf.Document`` in place.

    When ``max_pages_share < 1``, images reused on more than that share of
    pages are skipped (template chrome, not a watermark).

    Note: one ``delete_image`` call clears a *shared* xref document-wide, so
    only the first page carrying each xref is counted as cleaned.
    """
    result = CleanResult(pages_total=len(doc))
    if len(doc) == 0:
        return result
    # Snapshot candidate placements BEFORE mutating: deleting a shared xref
    # on one page neuters it everywhere, so later pages must not re-test.
    placements: dict = {}  # xref -> [page numbers using it as background]
    for pno, page in enumerate(doc):
        for xref in find_background_images(page, min_coverage, min_dimension_px):
            placements.setdefault(xref, []).append(pno)
    if max_pages_share < 1.0:
        limit = max_pages_share * len(doc)
        skipped = {x for x, pnos in placements.items() if len(pnos) > limit}
        if skipped:
            log.info("keeping template-chrome images: %s", sorted(skipped))
    else:
        skipped = set()

    cleaned_pages = set()
    for xref, pnos in placements.items():
        if xref in skipped:
            continue
        try:
            doc[pnos[0]].delete_image(xref)
        except ValueError:
            continue  # already gone
        cleaned_pages.update(pnos)
        result.removed_xrefs.append(xref)
    result.pages_cleaned = len(cleaned_pages)
    return result


def clean_bytes(data: bytes, min_coverage: float = 0.85,
                min_dimension_px: int = 400,
                max_pages_share: float = 1.0):
    """Clean PDF ``data``; return ``(cleaned_bytes, result)``.

    Raises ``ValueError`` for unreadable input (not a PDF, or encrypted --
    pass an already-decrypted document via :func:`clean_doc` instead).
    """
    import pymupdf

    result = CleanResult(bytes_before=len(data))
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"not a readable PDF ({exc})")
    if doc.needs_pass or doc.is_encrypted:
        # authenticate() with "" may succeed for empty user passwords
        try:
            ok = doc.authenticate("")
        except Exception:
            ok = False
        if not ok or doc.needs_pass:
            doc.close()
            raise ValueError("PDF is password-protected")
    try:
        inner = clean_doc(doc, min_coverage, min_dimension_px, max_pages_share)
    except Exception:
        doc.close()
        raise
    result.pages_total = inner.pages_total
    result.pages_cleaned = inner.pages_cleaned
    result.removed_xrefs = inner.removed_xrefs
    out = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    result.bytes_after = len(out)
    return bytes(out), result


def clean_file(src, dst=None, min_coverage: float = 0.85,
               min_dimension_px: int = 400, max_pages_share: float = 1.0,
               overwrite: bool = False):
    """Clean file ``src`` -> ``dst`` (default ``<stem>_clean.pdf``).

    Returns ``(Path(dst), CleanResult)``. With ``overwrite=True``, ``dst``
    may equal ``src`` (writes via a temp file + atomic replace). Raises
    ``FileNotFoundError`` / ``ValueError`` (bad PDF) / ``OSError``.
    """
    import pymupdf

    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"no such file: {src}")
    raw = src.read_bytes()
    try:
        pymupdf.open(stream=raw, filetype="pdf").close()
    except Exception as exc:
        raise ValueError(f"not a readable PDF: {src} ({exc})")
    if dst is None:
        dst = src.with_name(f"{src.stem}_clean{src.suffix or '.pdf'}")
    dst = Path(dst)
    if not overwrite and dst.resolve() == src.resolve():
        raise ValueError("dst == src without overwrite=True")

    out, result = clean_bytes(raw, min_coverage, min_dimension_px,
                              max_pages_share)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if overwrite and dst.resolve() == src.resolve():
        import os
        import tempfile

        fd, tmp = tempfile.mkstemp(dir=str(dst.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(out)
            os.replace(tmp, dst)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    else:
        dst.write_bytes(out)
    log.info("cleaned %s -> %s (%d/%d pages, %d -> %d bytes)",
             src, dst, result.pages_cleaned, result.pages_total,
             result.bytes_before, result.bytes_after)
    return dst, result


def main(argv=None) -> int:
    """CLI entry point (``box-dl-clean``): strip watermark backgrounds."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="box-dl-clean",
        description="Remove full-page watermark-background images from PDFs.",
    )
    parser.add_argument("pdfs", metavar="PDF", nargs="+",
                        help="PDF file(s) to clean")
    parser.add_argument("--out", dest="out", default=None,
                        help="Output file (single input only) or directory")
    parser.add_argument("--in-place", action="store_true",
                        help="Overwrite the input file(s)")
    parser.add_argument("--min-coverage", type=float, default=0.85,
                        help="Min page-area share to count as background (default: 0.85)")
    parser.add_argument("--min-size", type=int, default=400,
                        help="Min raster side in px (default: 400)")
    parser.add_argument("--max-pages-share", type=float, default=1.0,
                        help="Skip images reused on more than this share of pages "
                             "(e.g. 0.9 protects template chrome; default: 1.0 = off)")
    args = parser.parse_args(argv)

    if args.out and args.in_place:
        parser.error("--out and --in-place are mutually exclusive")
    if args.out and len(args.pdfs) > 1:
        out = Path(args.out)
        if not (out.is_dir() or not out.suffix):
            parser.error("--out with several inputs must be a directory")
    failures = 0
    for src in args.pdfs:
        try:
            if args.in_place:
                _dst, result = clean_file(src, src, args.min_coverage,
                                          args.min_size, args.max_pages_share,
                                          overwrite=True)
                print(f"OK  {src} ({result.pages_cleaned}/{result.pages_total} pages)")
            elif args.out:
                out = Path(args.out)
                dst = out / (f"{Path(src).stem}_clean.pdf") if out.is_dir() or not out.suffix else out
                _dst, result = clean_file(src, dst, args.min_coverage,
                                          args.min_size, args.max_pages_share)
                print(f"OK  {src} -> {_dst} "
                      f"({result.pages_cleaned}/{result.pages_total} pages)")
            else:
                _dst, result = clean_file(src, None, args.min_coverage,
                                          args.min_size, args.max_pages_share)
                print(f"OK  {src} -> {_dst} "
                      f"({result.pages_cleaned}/{result.pages_total} pages)")
        except (FileNotFoundError, ValueError, OSError) as exc:
            print(f"FAIL {src}: {exc}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
