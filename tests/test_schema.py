import pandas as pd
import pytest

from src.data_loader import hash_customer_id, validate_profile_schema


def test_profile_schema_accepts_required_columns():
    frame = pd.DataFrame(
        columns=[
            "customer_id",
            "gender",
            "age",
            "region",
            "job_classification",
            "date_joined",
            "balance",
        ]
    )
    validate_profile_schema(frame)


def test_profile_schema_rejects_missing_columns():
    with pytest.raises(ValueError, match="Missing required columns"):
        validate_profile_schema(pd.DataFrame(columns=["customer_id"]))


def test_hash_customer_id_is_repeatable_and_not_plaintext():
    digest = hash_customer_id("C123", "test-salt")
    assert digest == hash_customer_id("C123", "test-salt")
    assert digest != "C123"
    assert len(digest) == 64
