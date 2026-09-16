"""Optional, separate local Qwen3 reranker; normal LLM service needs no torch.

Run: python -m app.reranker_server --model /path/to/Qwen3-Reranker-0.6B
Weights must already exist locally; serving never downloads a model.
"""
import argparse
from threading import Lock
from typing import Annotated

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class RerankRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    documents: list[Annotated[str, Field(min_length=1, max_length=8000)]] = Field(min_length=1, max_length=64)


class QwenReranker:
    def __init__(self, model_path: str, device: str, max_length: int = 2048):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.max_length = max_length
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, padding_side="left", local_files_only=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path, local_files_only=True,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        ).to(device).eval()
        self.yes = self.tokenizer.convert_tokens_to_ids("yes")
        self.no = self.tokenizer.convert_tokens_to_ids("no")
        self.prefix = self.tokenizer.encode(
            '<|im_start|>system\nJudge whether the document answers the query under the instruction. Answer only "yes" or "no".<|im_end|>\n<|im_start|>user\n',
            add_special_tokens=False,
        )
        self.suffix = self.tokenizer.encode(
            "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n", add_special_tokens=False,
        )

    def score(self, query: str, documents: list[str]) -> list[float]:
        scores = []
        torch = self.torch
        # One pair at a time bounds memory on CPU laptops and small GPUs.
        with torch.inference_mode():
            for document in documents:
                header = (
                    "<Instruct>: Retrieve passages that answer this question about the presentation.\n"
                    "<Query>: "
                )
                available = self.max_length - len(self.prefix) - len(self.suffix)
                query_ids = self.tokenizer.encode(query, add_special_tokens=False)[:min(512, available // 4)]
                header_ids = self.tokenizer.encode(header, add_special_tokens=False)
                body_ids = header_ids + query_ids + self.tokenizer.encode("\n<Document>: ", add_special_tokens=False)
                # A long query must not consume the document's entire token budget.
                doc_ids = self.tokenizer.encode(document, add_special_tokens=False)[:available - len(body_ids)]
                ids = torch.tensor([self.prefix + body_ids + doc_ids + self.suffix], device=self.model.device)
                logits = self.model(input_ids=ids, attention_mask=torch.ones_like(ids)).logits[0, -1]
                scores.append(torch.softmax(logits[[self.no, self.yes]].float(), dim=-1)[1].item())
        return scores


def create_app(ranker) -> FastAPI:
    app = FastAPI(title="Local retrieval reranker")
    slot = Lock()

    @app.post("/rerank")
    def rerank(request: RerankRequest):
        if not slot.acquire(blocking=False):
            raise HTTPException(status_code=503, detail="Reranker is busy")
        try:
            scores = ranker.score(request.query, request.documents)
            return {"results": [{"index": index, "relevance_score": score}
                                for index, score in enumerate(scores)]}
        finally:
            slot.release()

    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Local downloaded model path")
    parser.add_argument("--device", choices=("cpu", "cuda", "mps"), default="cpu")
    parser.add_argument("--port", type=int, default=8003)
    parser.add_argument("--max-length", type=int, default=2048, choices=(2048, 4096, 8192))
    args = parser.parse_args()
    ranker = QwenReranker(args.model, args.device, args.max_length)
    uvicorn.run(create_app(ranker), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
