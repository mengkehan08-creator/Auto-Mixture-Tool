from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from quadmix.data.dataset_schema import DatasetSchema
from quadmix.data.metadata_manager import ShardMetadataManager
from quadmix.data.shard_io import _iter_json_array, iter_json_records
from quadmix.data.record_adapter import adapt_record
from quadmix_platform.service import PlatformService


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = DatasetSchema.from_yaml(str(ROOT / "configs" / "schema_stem.yaml"))
ADAPTED_SCHEMA = DatasetSchema.from_yaml(
    str(ROOT / "configs" / "schema_stem_sample_json.yaml")
)


def _record(text: str, domain: str, row_id: int) -> dict:
    return {
        "text": text,
        "category_name": domain,
        "stem_relevance": 0.9,
        "knowledge_value": 0.8,
        "notation_fidelity": 0.7,
        "rigor_coherence": 0.6,
        "noise_level": 0.1,
        "char_count_col": len(text),
        "source_record_idx": row_id,
    }


def _source_record(
    text: str = "A sufficiently long STEM training example.",
    category: str = "数理科学和化学-化学-分析化学",
    score: float = 0.8,
    relevance: int = 5,
) -> dict:
    return {
        "__id__": 123,
        "text": text,
        "status": "SUCCESS",
        "token_num": 256,
        "cut_text_len": len(text),
        "domain_category_cls_v1.3": [{"category_name": category, "score": score}],
        "stem_quality_eval": {
            "stem_domains": ["chemistry"],
            "stem_relevance": relevance,
            "knowledge_value": 5,
            "notation_fidelity": 5,
            "rigor_coherence": 4,
            "noise_level": 5,
            "duplication_suspect": "N",
            "correctness": "Y",
            "overall_verdict": "accept",
        },
    }


class JsonRecordReaderTests(unittest.TestCase):
    def test_json_array_is_streamed_across_small_chunks(self) -> None:
        values = list(_iter_json_array(io.StringIO('[{"a": 1}, {"a": 2}]'), chunk_size=5))
        self.assertEqual(values, [{"a": 1}, {"a": 2}])

    def test_json_extension_accepts_line_delimited_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "part.json"
            path.write_text(
                "\n\n" + "\n".join(json.dumps({"value": value}) for value in (1, 2)) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                list(iter_json_records(str(path))),
                [{"value": 1}, {"value": 2}],
            )


class JsonShardMetadataTests(unittest.TestCase):
    def test_manager_reads_json_metadata_and_selected_texts_without_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            records = [_record("alpha", "数学", 10), _record("beta", "物理", 20)]
            (nested / "part.json").write_text(json.dumps(records), encoding="utf-8")
            (root / "manifest.json").write_text('{"total_rows": 2}', encoding="utf-8")

            manager = ShardMetadataManager(str(root), schema=SCHEMA, max_workers=1)
            self.assertEqual(manager.num_docs, 2)
            self.assertEqual(manager.num_shards, 1)
            np.testing.assert_array_equal(manager.domain_labels, np.array([0, 3]))
            self.assertEqual(manager.read_texts(np.array([1, 0])), ["beta", "alpha"])

            cached = ShardMetadataManager(str(root), schema=SCHEMA, max_workers=1)
            self.assertEqual(cached.read_texts(np.array([0])), ["alpha"])

    def test_stem_adapter_maps_nested_fields_and_reports_filtering(self) -> None:
        accepted = _source_record()
        rejected = _source_record(relevance=2)
        adapted, reasons = adapt_record(accepted, ADAPTED_SCHEMA, 7)
        self.assertEqual(reasons, [])
        self.assertEqual(adapted["category_name"], "化学")
        self.assertEqual(adapted["stem_relevance"], 5.0)
        self.assertEqual(adapted["source_record_idx"], 7)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Match the actual extensionless shard naming convention.
            shard = root / "part-00003"
            shard.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in (rejected, accepted)),
                encoding="utf-8",
            )
            manager = ShardMetadataManager(
                str(root), schema=ADAPTED_SCHEMA, max_workers=1
            )
            self.assertEqual(manager.num_docs, 1)
            self.assertEqual(manager.read_texts(np.array([0])), [accepted["text"]])
            self.assertEqual(manager.filter_report["scanned"], 2)
            self.assertEqual(manager.filter_report["accepted"], 1)
            self.assertEqual(
                manager.filter_report["reasons"], {"stem_relevance_below_min": 1}
            )

    def test_five_observed_category_shapes_map_to_expected_domains(self) -> None:
        cases = {
            "数理科学和化学-化学-分析化学": "化学",
            "生物学/动物学-昆虫学": "生物学",
            "数理科学和化学-物理-高能物理学": "物理",
            "生物学/动物学-生态学": "生物学",
            "数理科学和化学-化学-高分子化学": "化学",
        }
        for category, expected in cases.items():
            with self.subTest(category=category):
                adapted, reasons = adapt_record(
                    _source_record(category=category), ADAPTED_SCHEMA, 0
                )
                self.assertEqual(reasons, [])
                self.assertEqual(adapted["category_name"], expected)

    def test_full_audit_reports_rejections_and_four_domain_coverage(self) -> None:
        categories = [
            "数理科学和化学-数学-基础数学",
            "数理科学和化学-化学-分析化学",
            "生物学/动物学-生态学",
            "数理科学和化学-物理-高能物理学",
        ]
        records = [_source_record(category=category) for category in categories]
        records.append(_source_record(category=categories[0], relevance=2))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "part-00003"
            path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in records),
                encoding="utf-8",
            )
            report = PlatformService(ROOT).inspect_dataset({
                "dataset_uri": directory,
                "schema_uri": str(ROOT / "configs" / "schema_stem_sample_json.yaml"),
                "dataset_id": "quadmix",
                "full_scan": True,
            })
        self.assertTrue(report["valid"], report["errors"])
        audit = report["full_audit"]
        self.assertEqual(audit["scanned"], 5)
        self.assertEqual(audit["accepted"], 4)
        self.assertEqual(audit["rejected"], 1)
        self.assertEqual(audit["rejection_reasons"], {"stem_relevance_below_min": 1})
        self.assertEqual(audit["domain_distribution"], {
            "数学": 1, "化学": 1, "生物学": 1, "物理": 1,
        })

    def test_fully_filtered_shard_does_not_report_missing_schema_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "part-00490").write_text(
                json.dumps(_source_record(relevance=2), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (root / "part-00491").write_text(
                json.dumps(_source_record(), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            report = PlatformService(ROOT).inspect_dataset({
                "dataset_uri": directory,
                "schema_uri": str(ROOT / "configs" / "schema_stem_sample_json.yaml"),
                "dataset_id": "quadmix",
                "sample_size": 2,
            })

        self.assertTrue(report["valid"], report["errors"])
        self.assertFalse(any("缺少" in error for error in report["errors"]))
        self.assertTrue(any(
            "part-00490" in warning and "stem_relevance_below_min" in warning
            for warning in report["warnings"]
        ))

    def test_rejected_invalid_records_do_not_fail_when_accepted_records_remain(self) -> None:
        invalid = _source_record()
        invalid.pop("stem_quality_eval")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "part-00490").write_text(
                json.dumps(invalid, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (root / "part-00491").write_text(
                json.dumps(_source_record(), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            report = PlatformService(ROOT).inspect_dataset({
                "dataset_uri": directory,
                "schema_uri": str(ROOT / "configs" / "schema_stem_sample_json.yaml"),
                "dataset_id": "quadmix",
                "sample_size": 2,
            })

        self.assertTrue(report["valid"], report["errors"])
        self.assertTrue(any(
            "part-00490" in warning and "missing_stem_quality_eval" in warning
            for warning in report["warnings"]
        ))

    def test_validation_fails_when_all_sampled_records_are_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for shard_name in ("part-00490", "part-00491"):
                (root / shard_name).write_text(
                    json.dumps(_source_record(relevance=2), ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            report = PlatformService(ROOT).inspect_dataset({
                "dataset_uri": directory,
                "schema_uri": str(ROOT / "configs" / "schema_stem_sample_json.yaml"),
                "dataset_id": "quadmix",
                "sample_size": 2,
            })

        self.assertFalse(report["valid"])
        self.assertTrue(any(
            "过滤" in error or "filters" in error
            for error in report["errors"]
        ))


if __name__ == "__main__":
    unittest.main()
