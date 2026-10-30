.PHONY: test demo

test:
	PYTHONPATH=src python -m pytest tests/ -q

demo:
	PYTHONPATH=src python -m data_migration_platform.cli demo
