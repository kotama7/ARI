# Requirements

- Python ≥ 3.13
- `mcp`, `litellm`, `jsonschema`
- LLM providers: at minimum one of OpenAI / Anthropic / Google Gemini API keys
- For PaperBench SimpleJudge integration (consumed by `ari-skill-paper-re`), see PaperBench's own dependencies

Generated rubrics are not standalone files: their exact model-call and repair
artifacts are written below `.ari-rubric/<output-stem>/`. Preserve that directory
with the rubric so an independent audit can verify the referenced bytes. V1
migration is offline and lossless; a legacy leaf that cannot be grounded in the
supplied paper causes migration to fail.

## Environment variables

| Variable | Required | Default |
|---|---|---|
| `ARI_MODEL_RUBRIC_GEN` | no | `gemini/gemini-2.5-pro` |
| `ARI_MODEL_RUBRIC_AUDIT` | no | `anthropic/claude-opus-4-7` |
| `ARI_LLM_API_BASE` | no | provider-specific |

Provider API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` / `GEMINI_API_KEY`) follow the standard `litellm` resolution rules.
