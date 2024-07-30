# %%
import argparse
import os, sys
#%%
parser = argparse.ArgumentParser()
parser.add_argument('--layers', type=int, default=4)
parser.add_argument('--heads', type=int, default=4)
parser.add_argument('--batch_size', type=int, default=48)
parser.add_argument('--lr', type=float, default=1e-3)
parser.add_argument('--epochs', type=int, default=100)
parser.add_argument('--gpus', type=str, default='0')
parser.add_argument('--nowandb', action='store_true', default=True)
args = parser.parse_args()
#%%
if not args.nowandb:
    os.environ["WANDB_PROJECT"] = "icd"
    os.environ["WANDB_LOG_MODEL"] = "end"
os.environ['CUDA_VISIBLE_DEVICES'] = args.gpus
import torch
import pickle as pk
import numpy as np
from transformers import BertConfig, BertForMaskedLM
from transformers import AutoTokenizer, TrainingArguments, Trainer, DataCollatorForLanguageModeling
from torch.utils.data import Dataset
import utils
#%%
with open('saved/diagnoses.pk', 'rb') as fl:
    dxs = pk.load(fl)
#%%
tokenizer = AutoTokenizer.from_pretrained('./saved/tokenizers/bert')
#%%
bertconfig = BertConfig(
    vocab_size=len(tokenizer.vocab),
    max_position_embeddings=tokenizer.model_max_length,
    hidden_size=192,
    num_hidden_layers=args.layers,
    num_attention_heads=args.heads,
    intermediate_size=1024,
)
model = BertForMaskedLM(bertconfig)
#%%
optimizer = torch.optim.AdamW(
    model.parameters(),
    lr=args.lr,
)
# %%
phase_ids = { phase: np.genfromtxt(f'artifacts/splits/{phase}_ids.txt') for phase in ['train', 'val', 'test'] }
phase_ids['val'] = phase_ids['val'][::10][:1024]
datasets = { phase: utils.ICDDataset(dxs, tokenizer, ids, separator='[SEP]') for phase, ids in phase_ids.items() }

data_collator = DataCollatorForLanguageModeling(
    tokenizer=tokenizer, mlm=True, mlm_probability=args.mask_ratio
)

training_args = TrainingArguments(
    output_dir=f'runs/bert-{args.arch}',
    per_device_train_batch_size=args.batch_size,
    per_device_eval_batch_size=16,
    learning_rate=args.lr,
    num_train_epochs=args.epochs,
    report_to='wandb' if not args.nowandb else None,
    evaluation_strategy='steps',
    run_name=f'gpt-{args.arch}',
    eval_steps=500,
    save_steps=1000,
)

def compute_metrics(eval_pred, mask_value=-100, topns=(1, 5, 10)):
    logits, labels = eval_pred
    bsize, seqlen = labels.shape

    logits = torch.from_numpy(np.reshape(logits, (bsize*seqlen, -1)))
    labels = torch.from_numpy(np.reshape(labels, (bsize*seqlen)))
    where_prediction = labels != mask_value

    topaccs = utils.accuracy(logits[where_prediction], labels[where_prediction], topk=topns)

    return { f'top{n:02d}': acc for n, acc in zip(topns, topaccs) }

trainer = Trainer(
    model=model,
    data_collator=data_collator,
    args=training_args,
    train_dataset=datasets['train'],
    eval_dataset=datasets['val'],
    compute_metrics=compute_metrics,
)
# %%
trainer.evaluate()
trainer.train()
# %%
torch.save(model.state_dict(), 'saved/bert_basic.pth')
# %%
