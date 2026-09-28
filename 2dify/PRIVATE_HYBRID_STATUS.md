# 2Dify private hybrid worker

This is a personal-use project, not a public deployment.

## Reality check
There is no honest way to promise unlimited *free* AI GPU inference. A hybrid design can avoid depending on one provider, but each remote provider still has its own quota, queue, and terms. This repo does not claim automatic access to Kaggle/Colab/Hugging Face GPUs.

## Current working entry point
- Colab notebook: `2dify/2Dify_Private_Colab.ipynb`
- Worker: `2dify/2dify_worker.py`
- Model endpoint: Hugging Face Space `decart-ai/lucy-edit-dev`

The worker currently uses Lucy directly. It splits a video into 81-frame windows (~3.375 seconds at 24 FPS), requests each window, then joins the returned silent clips. **This is not yet an unlimited multi-provider scheduler.** Each window is a separate inference request, and the Lucy Space can throttle, sleep, change API, or run out of free quota.

## Hybrid plan (manual provider selection for now)
1. Keep the browser/UI private and local; do not publish it.
2. Use the Colab notebook as the controller.
3. Run the same worker wherever a compatible GPU runtime is available.
4. If one runtime's quota ends, save the input and completed chunks, then resume on another runtime.
5. For truly no-daily-quota processing, use a computer with a compatible local GPU. CPU-only processing of this 5B video model is not a practical substitute.

## Important current limitation
The present worker does not yet checkpoint/resume completed chunks, automatically detect provider quotas, or switch providers. Those features need provider-specific authenticated worker endpoints. Never paste access tokens into a public repo or notebook shared with others.
