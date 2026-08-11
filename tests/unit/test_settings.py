from aula12_agents.settings import LabSettings


def test_settings_defaults_to_secret_free_mock(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = LabSettings(_env_file=None, run_db_path=tmp_path / "runs.sqlite3")

    report = settings.doctor_report()
    assert report["model_provider"] == "mock"
    assert report["langfuse_credentials_configured"] is False


def test_doctor_report_never_contains_openrouter_secret(tmp_path) -> None:
    settings = LabSettings(
        _env_file=None,
        model_provider="openrouter",
        openrouter_api_key="do-not-print-me",
        openrouter_primary_model="openai/gpt-4.1-mini",
        run_db_path=tmp_path / "runs.sqlite3",
    )
    assert "do-not-print-me" not in repr(settings.doctor_report())


def test_openrouter_model_does_not_depend_on_ollama_model(tmp_path) -> None:
    settings = LabSettings(
        _env_file=None,
        model_provider="openrouter",
        ollama_model="gemma4:26b-mlx",
        openrouter_api_key="do-not-print-me",
        openrouter_primary_model="qwen/qwen3.7-plus",
        openrouter_backup_model="poolside/laguna-s-2.1:free",
        run_db_path=tmp_path / "runs.sqlite3",
    )

    assert settings.provider_settings().model == "qwen/qwen3.7-plus"
    report = settings.doctor_report()
    assert report["openrouter_primary_model_configured"] is True
    assert report["openrouter_backup_model_configured"] is True


def test_legacy_provider_aliases_remain_compatible(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "legacy-model")
    settings = LabSettings(_env_file=None, run_db_path=tmp_path / "runs.sqlite3")

    provider = settings.provider_settings()

    assert provider.kind == "ollama"
    assert provider.model == "legacy-model"


def test_namespaced_provider_settings_take_precedence_over_legacy_aliases(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "current-model")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("LLM_MODEL", "legacy-model")
    settings = LabSettings(_env_file=None, run_db_path=tmp_path / "runs.sqlite3")

    provider = settings.provider_settings()

    assert provider.kind == "ollama"
    assert provider.model == "current-model"
