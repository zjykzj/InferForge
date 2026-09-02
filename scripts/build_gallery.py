#!/usr/bin/env python3
"""Build (or rebuild) the gallery index for the search/dupcheck apis.

Scans the gallery image directory, encodes every image with the embed engine
(the SAME one the worker serves requests with — the gallery is bound to the
embed default model, docs/embedding.md §5) and writes the vectors into a
milvus-lite db file.

Run it with the celery worker STOPPED: the db file is single-process
exclusive, and a rebuild while the worker holds it open would fail.

Usage:
    python3 scripts/build_gallery.py                              # gallery/ -> data/gallery.db
    python3 scripts/build_gallery.py --dir /path/to/gallery --db /tmp/gallery.db --force
    INFERFORGE_GALLERY_DIR=/path/to/gallery INFERFORGE_GALLERY_DB=/tmp/g.db python3 scripts/build_gallery.py
"""
import argparse
import logging
import os
import sys

# Project-root import (mirrors celery_app.py): scripts run from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Boot-time tool like scripts/preflight_models.py: never a metrics producer.
# start.sh exports PROMETHEUS_MULTIPROC_DIR, and prometheus_client's
# multiprocess mode writes one file per process at utils.metrics import
# (reached via the engines import chain below) — unsetting the env keeps the
# shared metrics dir free of this short-lived process's files.
os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)

import cv2

from tasks import embedding
from tasks.search import COLLECTION_NAME

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build the gallery index for the search/dupcheck apis (worker must be stopped)."
    )
    parser.add_argument("--dir", default=os.environ.get("INFERFORGE_GALLERY_DIR", "gallery"),
                        help="gallery image directory (default: $INFERFORGE_GALLERY_DIR or gallery/)")
    parser.add_argument("--db", default=os.environ.get("INFERFORGE_GALLERY_DB",
                                                       os.path.join("data", "gallery.db")),
                        help="milvus-lite db file to write (default: $INFERFORGE_GALLERY_DB or data/gallery.db)")
    parser.add_argument("--force", action="store_true",
                        help="rebuild even if the index already exists")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    args = parse_args()

    if not os.path.isdir(args.dir):
        print("[ERROR] gallery directory not found: %s" % args.dir)
        return 1
    files = sorted(
        os.path.join(args.dir, f) for f in os.listdir(args.dir)
        if os.path.splitext(f)[1].lower() in IMAGE_EXTS
    )
    if not files:
        print("[ERROR] no images found in %s" % args.dir)
        return 1

    from pymilvus import MilvusClient  # worker-only dep, imported on demand

    vectors = []
    rows = []
    skipped = 0
    for path in files:
        image = cv2.imread(path)
        if image is None:
            logging.getLogger("build_gallery").warning("unreadable image, skipped: %s", path)
            skipped += 1
            continue
        vector = embedding.encode(image)  # embed DEFAULT model, same as the worker
        rows.append({"id": os.path.basename(path), "path": path,
                     "vector": vector.astype("float32").tolist()})
    if not rows:
        print("[ERROR] no readable images in %s" % args.dir)
        return 1

    os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)
    client = MilvusClient(args.db)
    if client.has_collection(COLLECTION_NAME):
        if not args.force:
            print("[SKIP] index already exists at %s (use --force to rebuild)" % args.db)
            return 0
        client.drop_collection(COLLECTION_NAME)
        print("dropped existing collection: %s" % COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        dimension=rows[0]["vector"].__len__(),
        metric_type="COSINE",  # L2-normalized vectors -> cosine similarity
        auto_index=True,
        id_type="string",      # filenames as primary keys (default is int64)
        max_length=256,
    )
    client.insert(collection_name=COLLECTION_NAME, data=rows)
    print("[OK] indexed %d image(s) into %s (%d skipped)" % (len(rows), args.db, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
