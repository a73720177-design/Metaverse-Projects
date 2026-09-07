from scripts.serve_vllm import build_command


def test_build_vllm_command_for_quantized_model(monkeypatch):
    monkeypatch.setenv("VLLM_MODEL", "org/quantized-model")
    monkeypatch.setenv("VLLM_QUANTIZATION", "awq")
    monkeypatch.setenv("VLLM_MAX_MODEL_LEN", "8192")
    monkeypatch.setenv("VLLM_MAX_NUM_SEQS", "4")
    command = build_command()

    assert command[:3] == ["vllm", "serve", "org/quantized-model"]
    assert command[command.index("--quantization") + 1] == "awq"
    assert command[command.index("--max-model-len") + 1] == "8192"
    assert command[command.index("--max-num-seqs") + 1] == "4"
    assert command[command.index("--host") + 1] == "127.0.0.1"
