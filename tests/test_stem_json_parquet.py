from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from auto_mixture_tool.plugins.format_validators.stem_json_parquet import (
    StemJsonParquetDataset,
)
from quadmix.data.dataset_schema import DatasetSchema
from quadmix.data.record_adapter import adapt_record
from quadmix_platform.service import PlatformService
from scripts.platform.convert_stem_json_to_parquet import build_parquet_record


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCHEMA_PATH = ROOT / "configs" / "schema_stem_sample_json.yaml"
OUTPUT_SCHEMA_PATH = ROOT / "configs" / "schema_stem_quadmix_parquet.yaml"


def _source_record(relevance: int = 5) -> dict:
    return {
        "__id__": 123,
        "text": "A sufficiently long chemistry training example.",
        "status": "SUCCESS",
        "token_num": 256,
        "cut_text_len": 48,
        "domain_category_cls_v1.3": [
            {"category_name": "数理科学和化学-化学-分析化学", "score": 0.8},
            {"category_name": "数理科学和化学-物理-高能物理学", "score": 0.1},
        ],
        "stem_quality_eval": {
            "stem_domains": ["chemistry", "physics"],
            "stem_relevance": relevance,
            "knowledge_value": 5,
            "notation_fidelity": 4,
            "rigor_coherence": 4,
            "noise_level": 5,
            "duplication_suspect": "N",
            "correctness": "Y",
            "overall_verdict": "accept",
        },
    }


class StemJsonParquetTests(unittest.TestCase):
    def test_accepted_nested_record_maps_to_flat_algorithm_columns(self) -> None:
        source_schema = DatasetSchema.from_yaml(str(SOURCE_SCHEMA_PATH))
        output_schema = DatasetSchema.from_yaml(str(OUTPUT_SCHEMA_PATH))
        adapted, reasons = adapt_record(_source_record(), source_schema, 17)
        self.assertEqual(reasons, [])
        self.assertIsNotNone(adapted)

        record = build_parquet_record(adapted, source_schema, output_schema, 0)

        self.assertEqual(record["domain"], "化学")
        self.assertEqual(record["stem_relevance"], 5.0)
        self.assertEqual(record["knowledge_value"], 5.0)
        self.assertEqual(record["notation_fidelity"], 4.0)
        self.assertEqual(record["rigor_coherence"], 4.0)
        self.assertEqual(record["noise_level"], 5.0)
        self.assertEqual(record["char_count"], 48)
        self.assertEqual(record["source_record_idx"], 0)
        self.assertEqual(set(record), {
            "text", "domain", "stem_relevance", "knowledge_value",
            "notation_fidelity", "rigor_coherence", "noise_level",
            "char_count", "source_record_idx",
        })

    def test_plugin_builds_conversion_before_algorithm_and_uses_output_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "part-00000"
            dataset.write_text(
                json.dumps(_source_record(), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            service = PlatformService(ROOT)
            service.executors.get("local").submit = lambda job: (
                "SUCCEEDED", f"stub-{job.id}", "stubbed submission",
            )
            job = service.create_job({
                "dataset_uri": str(dataset),
                "schema_uri": str(SOURCE_SCHEMA_PATH),
                "dataset_id": "stem-json-parquet",
                "output_uri": str(root / "result"),
                "algorithm_id": "quadmix",
                "trainer_id": "nanochat",
                "evaluator_id": "stem",
                "executor_id": "local",
                "dataset_config": {"rows_per_group": 128, "compression": "zstd"},
                "algorithm_config": {"device_type": "cpu", "npu_devices": 1},
                "trainer_config": {"npu_devices": 1},
                "executor_config": {"device_type": "cpu", "device_count": 1},
            })

        self.assertEqual(
            [stage["name"] for stage in job["stages"]],
            [
                "dataset-filter-convert-parquet",
                "quadmix-selection",
                "nanochat-train-evaluate",
            ],
        )
        algorithm_args = job["stages"][1]["args"]
        schema_index = algorithm_args.index("--schema") + 1
        self.assertEqual(Path(algorithm_args[schema_index]), OUTPUT_SCHEMA_PATH)
        self.assertIn(
            "prepared_parquet_",
            job["stages"][2]["env"]["PREPROCESSED_DATA_DIR"],
        )
        self.assertEqual(
            Path(job["stages"][2]["env"]["SCHEMA_CONFIG"]),
            OUTPUT_SCHEMA_PATH,
        )

    def test_plugin_rejects_source_schema_without_stem_adapter(self) -> None:
        plugin = StemJsonParquetDataset()
        report = plugin.validate({
            "dataset_uri": str(ROOT / "examples" / "platform" / "sample_dataset.json"),
            "schema_uri": str(ROOT / "examples" / "platform" / "sample_schema.yaml"),
            "sample_size": 10,
        })
        self.assertFalse(report["valid"])
        self.assertTrue(any("record_adapter" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
