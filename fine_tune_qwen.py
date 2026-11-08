# -*- coding: utf-8 -*-
"""
基于 Qwen2.5-1.5B-Instruct 的 QLoRA 指令微调脚本
适配 trl 新版 API 及现代 llama.cpp 转换规范
用法：python fine_tune_qwen.py
"""
import os
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "true"

import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
)
from peft import (
    LoraConfig,
    get_peft_model,
    prepare_model_for_kbit_training,
    PeftModel,
)
from trl import SFTTrainer, SFTConfig

# ===================== 配置 =====================
MODEL_NAME = "Qwen/Qwen2.5-1.5B-Instruct"
DATA_PATH = "dataset/risk_sft_train.jsonl"
OUTPUT_DIR = "output_qwen_risk_lora"
MERGED_DIR = "output_qwen_risk_merged"
MAX_SEQ_LENGTH = 1024


# ===================== 数据格式化 =====================
def formatting_prompts_func(example):
    """返回单条 ChatML 字符串"""
    return (
        f"<|im_start|>system\n{example['instruction']}<|im_end|>\n"
        f"<|im_start|>user\n{example['input']}<|im_end|>\n"
        f"<|im_start|>assistant\n{example['output']}<|im_end|>"
    )


# ===================== 主流程 =====================
def main():
    print("1. 加载 Tokenizer 与基座模型（QLoRA 4-bit）...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token

    # 训练阶段：4-bit 量化加载，节省显存
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
    )

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)

    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj"
        ],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    print("2. 加载 SFT 数据集...")
    dataset = load_dataset("json", data_files=DATA_PATH, split="train")

    print("3. 配置 SFTConfig 并启动 SFTTrainer...")
    sft_config = SFTConfig(
        output_dir=OUTPUT_DIR,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        logging_steps=10,
        num_train_epochs=3,
        max_steps=100,            # 演示用，正式训练可删除此行
        optim="paged_adamw_8bit",
        fp16=True,
        save_strategy="steps",
        save_steps=50,
        max_length=MAX_SEQ_LENGTH,
    )

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        processing_class=tokenizer,
        formatting_func=formatting_prompts_func,
        args=sft_config,
    )

    trainer.train()

    print(f"4. 训练完成，正在保存 LoRA 适配器权重至 -> {OUTPUT_DIR}")
    trainer.model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

    # ========== 5. 合并 LoRA 权重（已修复 meta tensor 与设备冲突问题） ==========
    print("5. 正在将 LoRA 权重与基座模型进行合并 (Merge)...")

    merge_device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"   合并设备：{merge_device}")

    # 合并时必须加载【非量化】的完整基座模型
    base_model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.float16,
        device_map=None,
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    ).to(merge_device)

    merged_model = PeftModel.from_pretrained(
        base_model, OUTPUT_DIR, torch_dtype=torch.float16
    )
    merged_model = merged_model.merge_and_unload()

    # 移回 CPU 保存，防止张量分片保存报错
    merged_model = merged_model.to("cpu")

    merged_model.save_pretrained(MERGED_DIR)
    tokenizer.save_pretrained(MERGED_DIR)
    print(f"✅ 全量合并模型已成功导出至：{MERGED_DIR}")


if __name__ == "__main__":
    main()
