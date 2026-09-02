#!/usr/bin/env python3
"""Export DINOv2 (ViT-S/14 or ViT-B/14) to ONNX for engines/dinov2.py.

One-off tool: torch/torchvision are export-time dependencies only, not
service dependencies (same role as `yolo export` for the other models —
the service never imports torch). The export matches the engine's
preprocessing exactly: raw RGB 224x224 input (the engine feeds [0,1] pixels,
ImageNet normalization stays OUTSIDE the graph — engines/dinov2.py does it),
output (1, 257, 384) token sequence — the engine takes token 0 (CLS) and
L2-normalizes it.

Weights come from facebookresearch/dinov2 via torch.hub — CC-BY-NC-4.0
(non-commercial), see docs/embedding.md §3.1; a commercial deployment
should substitute a permitted backbone.

Requirements (one-off): pip install torch torchvision onnxruntime

Usage:
    python3 scripts/export_dinov2.py                  # -> models/dino2-small.onnx
    python3 scripts/export_dinov2.py --size base      # dinov2_vitb14, 768-d (not the template default)
    python3 scripts/export_dinov2.py --output /tmp/dino2-small.onnx
"""
import argparse
import os
import sys

# Project-root import (mirrors celery_app.py): scripts run from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ARCHS = {
    "small": ("dinov2_vits14", 384),
    "base": ("dinov2_vitb14", 768),
}

INPUT_SIZE = 224  # ViT-*/14: 224 = 16x16 patches


def parse_args():
    parser = argparse.ArgumentParser(
        description="Export DINOv2 to ONNX (preprocessing matches engines/dinov2.py)."
    )
    parser.add_argument("--output", default=os.path.join("models", "dino2-small.onnx"),
                        help="output ONNX path (default: models/dino2-small.onnx)")
    parser.add_argument("--size", choices=sorted(ARCHS), default="small",
                        help="backbone size (default: small — the template's embed default)")
    return parser.parse_args()


def main():
    args = parse_args()
    hub_name, dim = ARCHS[args.size]

    import torch  # export-time dep only (never imported by the service)

    print("loading %s from torch.hub (facebookresearch/dinov2)..." % hub_name)
    backbone = torch.hub.load("facebookresearch/dinov2", hub_name)
    backbone.eval()

    class TokenSequenceWrapper(torch.nn.Module):
        """Pin the export contract: single `images` input -> (1, 257, dim)
        token sequence with the CLS token first.

        The hub backbone's forward_features returns a DICT (multi-output
        API); exporting it directly flattens the dict into several outputs
        and leaks its `masks` entry as a bogus graph input. This wrapper
        selects the two keys the engine uses (CLS + patch tokens) and
        concatenates them back into the classic token sequence.
        """

        def __init__(self, backbone):
            super().__init__()
            self.backbone = backbone

        def forward(self, x):
            features = self.backbone.forward_features(x)
            cls = features["x_norm_clstoken"].unsqueeze(1)   # (B, 1, D)
            patches = features["x_norm_patchtokens"]         # (B, N, D)
            return torch.cat((cls, patches), dim=1)

    model = TokenSequenceWrapper(backbone)
    model.eval()

    dummy = torch.randn(1, 3, INPUT_SIZE, INPUT_SIZE)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    # Static batch=1 (the engine always runs single-image) and the legacy
    # exporter (dynamo=False): torch>=2.6 defaults to the new dynamo
    # exporter, which rejects dynamic_axes and may not capture this model.
    torch.onnx.export(
        model, dummy, args.output,
        input_names=["images"], output_names=["output"],
        opset_version=17,
        dynamo=False,
    )
    print("[OK] exported: %s" % args.output)

    # Sanity check: reload with onnxruntime and confirm the output shape —
    # the engine expects (batch, 257, dim) with the CLS token first.
    import numpy as np
    import onnxruntime

    session = onnxruntime.InferenceSession(args.output, providers=["CPUExecutionProvider"])
    output = session.run(None, {"images": np.zeros((1, 3, INPUT_SIZE, INPUT_SIZE),
                                                   dtype=np.float32)})[0]
    print("[OK] output shape: %s (expect (1, 257, %d))" % (tuple(output.shape), dim))
    if output.shape != (1, 257, dim):
        print("[ERROR] unexpected output shape — the export does not match "
              "engines/dinov2.py expectations")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
