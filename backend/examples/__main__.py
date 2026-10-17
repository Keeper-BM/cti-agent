"""Run with uv run python -m backend.examples; --json prints the connected contracts."""

import argparse

from backend.examples.assessment import load_assessment_example


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the fixed synthetic assessment example")
    parser.add_argument("--json", action="store_true", help="Print the complete input/output JSON")
    args = parser.parse_args()
    example = load_assessment_example()
    if args.json:
        print(example.model_dump_json(indent=2))
    else:
        packages = {item.package_id: item for item in example.inventory.packages}
        print("PASS: synthetic inventory → normalized feed → expected findings → cited explanation")
        for finding in example.expected_findings:
            print(f"{packages[finding.package_ref].binary_name}: {finding.verdict}")
        print(
            "Fixed test data only; no SSH, network feed, version comparison, or LLM was executed."
        )


if __name__ == "__main__":
    main()
