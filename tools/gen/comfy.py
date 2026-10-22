"""Minimal ComfyUI API client for generating storyboard illustrations."""

from __future__ import annotations

import json
import shutil
import time
import urllib.request
import uuid
from pathlib import Path

SERVER = "http://127.0.0.1:8188"
COMFY_OUT = Path(__file__).resolve().parent.parent / "ComfyUI" / "output"


def _post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        SERVER + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def _get(path: str) -> dict:
    with urllib.request.urlopen(SERVER + path) as resp:
        return json.load(resp)


def generate(graph: dict, out_path: Path, timeout: float = 900) -> Path:
    client_id = uuid.uuid4().hex
    prompt_id = _post("/prompt", {"prompt": graph, "client_id": client_id})["prompt_id"]
    started = time.time()
    while time.time() - started < timeout:
        history = _get(f"/history/{prompt_id}")
        if prompt_id in history:
            entry = history[prompt_id]
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, indent=2)[-3000:])
            images = entry["outputs"]["9"]["images"]
            source = COMFY_OUT / images[0]["subfolder"] / images[0]["filename"]
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, out_path)
            return out_path
        time.sleep(1.0)
    raise TimeoutError("ComfyUI did not finish in time")


def graph(
    positive: str,
    negative: str,
    *,
    width: int = 1216,
    height: int = 704,
    steps: int = 24,
    cfg: float = 6.0,
    seed: int = 1234,
    control_image: str | None = None,
    control_strength: float = 0.85,
    ipadapter_image: str | None = None,
    ipadapter_weight: float = 0.75,
    ckpt: str = "sd_xl_base_1.0.safetensors",
) -> dict:
    g = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive, "clip": ["1", 1]},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "rehab"}},
    }

    model = ["1", 0]
    pos, neg = ["2", 0], ["3", 0]

    if control_image:
        g["7"] = {"class_type": "LoadImage", "inputs": {"image": control_image}}
        g["8"] = {
            "class_type": "ControlNetLoader",
            "inputs": {"control_net_name": "xinsir-openpose-sdxl.safetensors"},
        }
        g["10"] = {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {
                "positive": pos,
                "negative": neg,
                "control_net": ["8", 0],
                "image": ["7", 0],
                "strength": control_strength,
                "start_percent": 0.0,
                "end_percent": 1.0,
            },
        }
        pos, neg = ["10", 0], ["10", 1]

    if ipadapter_image:
        g["11"] = {"class_type": "LoadImage", "inputs": {"image": ipadapter_image}}
        g["12"] = {
            "class_type": "IPAdapterUnifiedLoader",
            "inputs": {"model": model, "preset": "PLUS (high strength)"},
        }
        g["13"] = {
            "class_type": "IPAdapterAdvanced",
            "inputs": {
                "model": ["12", 0],
                "ipadapter": ["12", 1],
                "image": ["11", 0],
                "weight": ipadapter_weight,
                "weight_type": "style transfer",
                "combine_embeds": "concat",
                "start_at": 0.0,
                "end_at": 1.0,
                "embeds_scaling": "V only",
            },
        }
        model = ["13", 0]

    g["5"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model,
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": "dpmpp_2m",
            "scheduler": "karras",
            "positive": pos,
            "negative": neg,
            "latent_image": ["4", 0],
            "denoise": 1.0,
        },
    }
    return g
