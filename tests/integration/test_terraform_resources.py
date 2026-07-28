"""Asserts the real infra/ Terraform config actually creates everything the
architecture calls for, against the test moto_server -- not just that
`terraform apply` exits 0. Mirrors the ev-charging-gap-analysis sibling's
own negative assertions (Step Functions/EventBridge absent by default),
extended for this project's Kinesis stream and 6 Lambda handlers."""
import json
import subprocess

from tests.conftest import INFRA_DIR, TEST_TFSTATE


def _state_list(terraform_bin) -> list[str]:
    result = subprocess.run(
        [terraform_bin, f"-chdir={INFRA_DIR}", "state", "list", f"-state={TEST_TFSTATE}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().splitlines()


def test_all_expected_resources_exist(applied_infra, terraform_bin):
    resources = _state_list(terraform_bin)

    expected_lambdas = {
        'aws_lambda_function.pipeline["ingest_opensky_states"]',
        'aws_lambda_function.pipeline["ingest_kinesis_consumer"]',
        'aws_lambda_function.pipeline["ingest_gdelt"]',
        'aws_lambda_function.pipeline["transform_silver"]',
        'aws_lambda_function.pipeline["transform_gold"]',
        'aws_lambda_function.pipeline["load_serving"]',
    }
    expected_tables = {
        "aws_dynamodb_table.traffic_by_region",
        "aws_dynamodb_table.conflict_events",
        "aws_dynamodb_table.pipeline_manifest",
    }
    expected_iam_roles = {
        "aws_iam_role.lambda_ingest",
        "aws_iam_role.lambda_transform",
        "aws_iam_role.lambda_serving",
    }

    assert expected_lambdas <= set(resources)
    assert expected_tables <= set(resources)
    assert expected_iam_roles <= set(resources)
    assert "aws_s3_bucket.data_lake" in resources

    # Kinesis is genuinely exercised against moto (real PutRecords/GetRecords
    # semantics) -- unlike Step Functions/Glue/Athena/EventBridge, it's not
    # gated behind an enable_x flag, so it must always be present.
    assert "aws_kinesis_stream.opensky_states" in resources

    # real-AWS-only resources must NOT be created against moto (default var values)
    assert not any("aws_sfn_state_machine" in r for r in resources)
    assert not any("aws_scheduler_schedule" in r for r in resources)
    assert not any("aws_glue" in r for r in resources)
    assert not any("aws_athena" in r for r in resources)
    assert not any("lifecycle_configuration" in r for r in resources)


def _show_state(terraform_bin) -> dict:
    result = subprocess.run(
        [terraform_bin, f"-chdir={INFRA_DIR}", "show", "-json", TEST_TFSTATE],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_traffic_table_has_status_ranked_gsi(applied_infra, terraform_bin):
    state = _show_state(terraform_bin)
    resources = state["values"]["root_module"]["resources"]
    traffic_table = next(r for r in resources if r["address"] == "aws_dynamodb_table.traffic_by_region")
    gsi_names = [gsi["name"] for gsi in traffic_table["values"]["global_secondary_index"]]
    assert "gsi1_status_ranked" in gsi_names


def test_conflict_events_table_has_region_by_time_gsi(applied_infra, terraform_bin):
    state = _show_state(terraform_bin)
    resources = state["values"]["root_module"]["resources"]
    events_table = next(r for r in resources if r["address"] == "aws_dynamodb_table.conflict_events")
    gsi_names = [gsi["name"] for gsi in events_table["values"]["global_secondary_index"]]
    assert "gsi1_region_by_time" in gsi_names


def test_kinesis_stream_has_one_shard(applied_infra, terraform_bin):
    state = _show_state(terraform_bin)
    resources = state["values"]["root_module"]["resources"]
    stream = next(r for r in resources if r["address"] == "aws_kinesis_stream.opensky_states")
    assert stream["values"]["shard_count"] == 1
