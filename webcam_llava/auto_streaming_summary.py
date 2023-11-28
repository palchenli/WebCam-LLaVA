import argparse
import datetime
import json
import os
import time
import io
import base64
import numpy as np

import gradio as gr
import requests

from llava.conversation import (default_conversation, conv_templates,
                                   SeparatorStyle)
from llava.constants import LOGDIR
from llava.utils import (build_logger, server_error_msg,
    violates_moderation, moderation_msg)
from PIL import Image
from sentence_transformers import SentenceTransformer
import hashlib


logger = build_logger("gradio_web_server", "gradio_web_server.log")

# no_change_btn = gr.Button.update()
# enable_btn = gr.Button.update(interactive=True)
# disable_btn = gr.Button.update(interactive=False)

priority = {
    "vicuna-13b": "aaaaaaa",
    "koala-13b": "aaaaaab",
}

total_num = 0
captions_cand = []
captions_all = []
encoder = SentenceTransformer('hfl/chinese-roberta-wwm-ext-large')


def get_conv_log_filename():
    t = datetime.datetime.now()
    name = os.path.join(LOGDIR, f"{t.year}-{t.month:02d}-{t.day:02d}-conv.json")
    return name


def get_model_list():
    ret = requests.post(args.controller_url + "/refresh_all_workers")
    assert ret.status_code == 200
    ret = requests.post(args.controller_url + "/list_models")
    models = ret.json()["models"]
    models.sort(key=lambda x: priority.get(x, x))
    logger.info(f"Models: {models}")
    return models


def get_summarization():
    global captions_cand
    content = " Then, ".join(captions_cand)
    content = "First, " + content[:1400]
    summarization = []

    # print(content)

    pload = {
        "model": "llava-v1.5-13b",
        "prompt": "A chat between a curious human and an artificial intelligence assistant. The assistant gives helpf"
                  "ul, detailed, and polite answers to the human's questions. USER: This is a textual description of"
                  " a video: \"{}\" If the above is descriptions of what the person in the video is doing, Please br"
                  "iefly describe in one sentence what the people in the video are doing in order. ASSISTANT:".format(content),
        "temperature": float("0.2"),
        "top_p": float("0.7"),
        "max_new_tokens": 1500,
        "stop": "</s>",
        "images": [],
    }

    try:
        # Stream output
        response = requests.post(
            "http://localhost:40000/worker_generate_stream",
            headers={'User-Agent': 'LLaVA Client'},
            json=pload,
            stream=False,
            timeout=10
        )
        for chunk in response.iter_lines(decode_unicode=False, delimiter=b"\0"):
            if chunk:
                tmp = json.loads(chunk.decode())
                summarization.append(tmp["text"][len(pload['prompt']):].strip())
    except requests.exceptions.RequestException as e:
        print("error")
        return "Req Error"

    print("*"*50)
    print(summarization[-1])
    print("*"*50)


def process(img):
    i = 1
    if i > 0:
        pload = {
            "model": "llava-v1.5-13b",
            "prompt": "A chat between a curious human and an artificial intelligence assistant. The assistant gives hel"
                      "pful, detailed, and polite answers to the human's questions. USER: <image>\nUse a simple senten"
                      "ce to describe what the person in the picture is doing？ ASSISTANT:",
            "temperature": float("0.2"),
            "top_p": float("0.7"),
            "max_new_tokens": 512,
            "stop": "</s>",
            "images": [],
        }
        image = Image.fromarray(img)
        image_data = io.BytesIO()
        image.save(image_data, format='JPEG')
        image_data_bytes = image_data.getvalue()
        encoded_image = base64.b64encode(image_data_bytes).decode('utf-8')

        pload["images"].append(encoded_image)
        answers = []

        try:
            # Stream output
            response = requests.post(
                "http://localhost:40000/worker_generate_stream",
                headers={'User-Agent': 'LLaVA Client'},
                json=pload,
                stream=False,
                timeout=10
            )
            for chunk in response.iter_lines(decode_unicode=False, delimiter=b"\0"):
                if chunk:
                    tmp = json.loads(chunk.decode())
                    answers.append(tmp["text"][len(pload['prompt']):].strip())
        except requests.exceptions.RequestException as e:
            print("error")
            return "Req Error"

        # print(answers[-1])
        global captions_cand
        if len(captions_cand) > 0:
            last_embed = encoder.encode(captions_cand[-1])
            cand_embed = encoder.encode(answers[-1])
            sim = np.dot(last_embed, cand_embed.T)
            sim = sim / (np.sqrt(np.dot(last_embed, last_embed.T)) * np.sqrt(np.dot(cand_embed, cand_embed.T)))
            print(str(sim), answers[-1])
            if sim < 0.96:
                captions_cand.append(answers[-1])
        else:
            captions_cand.append(answers[-1])

        captions_all.append(answers[-1])

        if len(captions_all) % 10 == 0:
            get_summarization()
            captions_cand = []

        return answers[-1]



demo = gr.Interface(
    fn=process,
    inputs=[
        gr.Image(source="webcam", streaming=True),
    ],
    #outputs=["image", "text"],
    outputs=["text"],
    live=True
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int)
    parser.add_argument("--controller-url", type=str, default="http://localhost:21001")
    parser.add_argument("--concurrency-count", type=int, default=10)
    parser.add_argument("--model-list-mode", type=str, default="once",
                        choices=["once", "reload"])
    parser.add_argument("--share", action="store_true")
    parser.add_argument("--moderate", action="store_true")
    parser.add_argument("--embed", action="store_true")
    args = parser.parse_args()
    logger.info(f"args: {args}")

    models = get_model_list()

    logger.info(args)

    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share
    )

