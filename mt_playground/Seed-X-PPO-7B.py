from vllm import LLM, SamplingParams, BeamSearchParams # windows不能直接用，需要走wsl2

model_path = "./ByteDance-Seed/Seed-X-PPO-7B"

model = LLM(model=model_path,
            max_num_seqs=512,
            tensor_parallel_size=8,
            enable_prefix_caching=True, 
            gpu_memory_utilization=0.95)

messages = [
    # without CoT
    "Translate the following English sentence into Chinese:\nMay the force be with you <zh>",
    # with CoT
    "Translate the following English sentence into Chinese and explain it in detail:\nMay the force be with you <zh>" 
]

# Beam search (We recommend using beam search decoding)
decoding_params = BeamSearchParams(beam_width=4,
                                   max_tokens=512)
# Greedy decoding
# decoding_params = SamplingParams(temperature=0,
#                                  max_tokens=512,
#                                  skip_special_tokens=True)

results = model.generate(messages, decoding_params)
responses = [res.outputs[0].text.strip() for res in results]

print(responses)
