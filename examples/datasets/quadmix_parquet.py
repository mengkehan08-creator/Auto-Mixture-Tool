"""Run in the data preparation environment; upload prepared_parquet/ to OBS."""
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

rows = [{
    "domain": "数学", "text": "勾股定理：直角三角形两条直角边的平方和等于斜边的平方。",
    "stem_relevance": 0.95, "knowledge_value": 0.9,
    "notation_fidelity": 0.9, "rigor_coherence": 0.9, "noise_level": 0.05,
    "source_record_idx": 0,
}]
for row in rows:
    row["char_count"] = len(row["text"])
output = Path("prepared_parquet")
output.mkdir(exist_ok=True)
pq.write_table(pa.Table.from_pylist(rows), output / "part-00000.parquet")
