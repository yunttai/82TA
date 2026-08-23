PYTHON ?= python
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)

.PHONY: validate layout contracts-lock contracts-update openapi openapi-examples harness-registry harness-evals snapshot-service snapshot-routing snapshot-integration context-parity manifest tree

validate:
	cd $(ROOT) && $(PYTHON) src/scripts/validate_repository.py

layout:
	cd $(ROOT) && $(PYTHON) src/scripts/validate_repository.py --layout-only

contracts-lock:
	cd $(ROOT) && $(PYTHON) src/scripts/verify_contract_lock.py

contracts-update:
	cd $(ROOT) && $(PYTHON) src/scripts/update_contract_lock.py --approved-change

openapi:
	cd $(ROOT) && $(PYTHON) src/scripts/validate_openapi.py

openapi-examples:
	cd $(ROOT) && $(PYTHON) src/scripts/validate_openapi_examples.py

harness-registry:
	cd $(ROOT) && $(PYTHON) src/scripts/validate_harness_registry.py

harness-evals:
	cd $(ROOT) && $(PYTHON) src/scripts/validate_harness_evals.py

snapshot-service:
	cd $(ROOT) && $(PYTHON) src/scripts/snapshot_context.py service-product

snapshot-routing:
	cd $(ROOT) && $(PYTHON) src/scripts/snapshot_context.py routing-intelligence

snapshot-integration:
	cd $(ROOT) && $(PYTHON) src/scripts/snapshot_context.py integration

context-parity:
	cd $(ROOT) && $(PYTHON) src/scripts/compare_context_snapshots.py

manifest:
	cd $(ROOT) && $(PYTHON) src/scripts/generate_package_manifest.py

tree:
	cd $(ROOT) && $(PYTHON) src/scripts/render_tree.py
