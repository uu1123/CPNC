import pytest
import requests
import uuid
import sales_validation


class TestUUIDGeneration:

    def test_uuid_api_connection(self):
        try:
            response = requests.get(
                "https://www.uuidtools.com/api/generate/v1",
                timeout=3
            )

            assert response.status_code == 200, (
                f"Expected status code 200, got {response.status_code}"
            )

            print("UUID API connection test passed")

        except requests.RequestException as e:
            pytest.skip(f"UUID API is unavailable: {e}")

    def test_generate_uuid_returns_uuid(self):
        logger = sales_validation.LoggerManager(None)

        result = logger.generate_uuid()

        assert isinstance(result, str), "Result should be a string"
        assert len(result) == 36, "UUID should contain 36 characters"

        uuid.UUID(result)

        print(f"UUID generation test passed: {result}")

    def test_generate_uuid_fallback(self, monkeypatch):
        logger = sales_validation.LoggerManager(None)

        def failed_request(*args, **kwargs):
            raise requests.RequestException("Connection failed")

        monkeypatch.setattr(
            sales_validation.requests,
            "get",
            failed_request
        )

        monkeypatch.setattr(
            sales_validation.uuid,
            "uuid4",
            lambda: "12345678-1234-4234-8234-123456789abc"
        )

        result = logger.generate_uuid()

        assert result == "12345678-1234-4234-8234-123456789abc"

        print("UUID fallback test passed")