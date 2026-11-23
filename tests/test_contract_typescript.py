from islandos_core import contract_schemas


def test_committed_typescript_matches_the_contract() -> None:
    """The viewer builds against a generated file; drift has to fail here, not in the browser."""
    generated = contract_schemas.typescript_source()
    committed = contract_schemas.TS_PATH.read_text(encoding="utf-8")
    assert committed == generated


def test_typescript_names_the_shared_shapes() -> None:
    text = contract_schemas.typescript_source()
    assert "export interface RunRequest {" in text
    assert "export interface RunResultSummary {" in text
    assert "export interface DeviceFlexibilitySummary {" in text
    assert "export interface AnnualProjection {" in text
    assert "page_inputs: RunRequestPageInputs | null;" in text
    assert "tasks: DeviceTask[];" in text
    assert "scheduled_energy_charge: number;" in text
    assert "days_equivalent_per_year: number;" in text
