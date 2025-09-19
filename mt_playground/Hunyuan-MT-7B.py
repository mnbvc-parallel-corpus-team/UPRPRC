# 跑一份在4070Ti上要等超过20分钟，不考虑
import datetime
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import datasets

WD = Path(__file__).parent

ds = datasets.load_from_disk(WD.parent / "DS_rework")["train"].select(range(10))

model_name_or_path = "tencent/Hunyuan-MT-7B"

tokenizer = AutoTokenizer.from_pretrained(model_name_or_path)
model = AutoModelForCausalLM.from_pretrained(model_name_or_path, device_map="auto")  # You may want to use bfloat16 and/or move to GPU here

def T(t: str):
    messages = [
        {"role": "user", "content": f"Translate the following segment into English, without additional explanation.\n\n{t}"},
    ]
    tokenized_chat = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=False,
        return_tensors="pt"
    )

    outputs = model.generate(tokenized_chat.to(model.device), max_new_tokens=2048)
    output_text = tokenizer.decode(outputs[0])
    print(type(output_text), output_text)
    return output_text

def mapfunc(row):
    for lang in ["ar", "de", "es", "fr", "ru", "zh"]:
        for e in row[lang].split('\n\n'):
            if e:
                T(e)

if __name__ == "__main__":
    begintime = datetime.datetime.now()
    print("bench start at", begintime)
    ds.map(mapfunc)
    print("bench end:", (datetime.datetime.now()-begintime).total_seconds())
