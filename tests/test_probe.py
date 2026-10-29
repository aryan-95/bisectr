from botocore.exceptions import ClientError
import pytest

from bisectr import probe
from bisectr.config import Config, Infra


def make_config():
    return Config(infra=Infra(
        region="r", cluster="c", log_group="g", exec_role="e", sg="s", subnets=["a"],
        image_repo="account.dkr.ecr.region.amazonaws.com/repository",
        runner_image="account.dkr.ecr.region.amazonaws.com/runner:latest",
    ))


def test_image_exists_returns_false_for_missing_tag(monkeypatch):
    class FakeEcr:
        def describe_images(self, **_kwargs):
            raise ClientError(
                {"Error": {"Code": "ImageNotFoundException", "Message": "missing"}},
                "DescribeImages",
            )

    monkeypatch.setattr(probe, "_ecr", lambda _region: FakeEcr())

    assert not probe.image_exists(make_config(), "missing-sha")


def test_image_exists_does_not_hide_aws_authorization_errors(monkeypatch):
    class FakeEcr:
        def describe_images(self, **_kwargs):
            raise ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
                "DescribeImages",
            )

    monkeypatch.setattr(probe, "_ecr", lambda _region: FakeEcr())

    with pytest.raises(ClientError, match="denied"):
        probe.image_exists(make_config(), "sha")
