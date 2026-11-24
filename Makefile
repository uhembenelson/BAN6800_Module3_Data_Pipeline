.PHONY: install test run dag docker-build docker-run clean verify

install:
	python -m pip install -r requirements.txt

test:
	python -m pytest

run:
	python -m flows.local_runner

dag:
	python -m flows.bank_pipeline_flow

docker-build:
	docker build -t ban6800-module3-pipeline:1.0.0 .

docker-run:
	docker run --rm -e PIPELINE_HASH_SALT="$${PIPELINE_HASH_SALT:?set it}" \
		-v "$$PWD/artifacts:/app/artifacts" ban6800-module3-pipeline:1.0.0

clean:
	rm -rf artifacts/*.json artifacts/*.csv artifacts/figures data/interim/*.csv data/processed/*.csv
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

verify: test run
	@echo "Artifacts in artifacts/ :"
	@ls -1 artifacts
