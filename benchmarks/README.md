# PANORAMA Benchmarks

This directory contains three benchmark tasks derived from the PANORAMA dataset, each representing a key step in the patent examination process. These benchmarks are designed to evaluate language models' capabilities in different aspects of patent analysis.

## Overview of Benchmark Tasks

The PANORAMA dataset captures the end-to-end examination workflow and the underlying reasons for patent applications. Based on real-world patent examination procedures, we divide this workflow into three benchmark tasks that replicate the main steps taken by examiners:

### 1. Prior-Art Retrieval for Patent Claims (PAR4PC)

**Task Description:** Select the document(s) from a pool of candidate prior-art documents that must be consulted to determine whether a target claim should be rejected.

**Directory:** [`par4pc/`](./par4pc/)

### 2. Paragraph Identification for Patent Claims (PI4PC)

**Task Description:** Given a claim and a prior-art document, identify the paragraph number within the document that should be compared with the claim when assessing patentability.

**Directory:** [`pi4pc/`](./pi4pc/)

### 3. Novelty and Non-Obviousness Classification for Patent Claims (NOC4PC)

**Task Description:** Given a claim and the cited prior-art documents with the relevant paragraphs, determine whether the claim is novel and non-obvious in relation to that prior art.

**Directory:** [`noc4pc/`](./noc4pc/)

## Using the Benchmarks

Each benchmark directory contains:

- Evaluation scripts
- Sample data (where applicable)
- Detailed README with specific instructions

### Data Format

The benchmark tasks use data from the PANORAMA dataset available on Hugging Face:

- [DxD-Lab/PANORAMA-NOC4PC-Bench](https://huggingface.co/datasets/DxD-Lab/PANORAMA-NOC4PC-Bench)
- [DxD-Lab/PANORAMA-PAR4PC-Bench](https://huggingface.co/datasets/DxD-Lab/PANORAMA-PAR4PC-Bench)
- [DxD-Lab/PANORAMA-PI4PC-Bench](https://huggingface.co/datasets/DxD-Lab/PANORAMA-PI4PC-Bench)

### Common Evaluation Commands

#### NOC4PC Evaluation:

```bash
python benchmarks/noc4pc/inference.py --provider [provider] --model [model] --prompt_mode [mode]
```

#### PAR4PC Evaluation:

```bash
# See specific benchmark directory for detailed parameters
python benchmarks/par4pc/evaluation.py
```

#### PI4PC Evaluation:

```bash
# See specific benchmark directory for detailed parameters
python benchmarks/pi4pc/evaluation.py
```
