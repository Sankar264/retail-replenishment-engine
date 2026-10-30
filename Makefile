PY ?= python
SCALE ?= starter

.PHONY: install generate generate-full validate test reproduce zip clean
install:
	$(PY) -m pip install -r requirements.txt

generate:            ## starter dataset (fast) -> data/starter
	$(PY) -m src.pipeline --scale starter --out data/starter

generate-full:       ## 2,000 SKUs x 100 stores x 365 days -> data/full (large)
	$(PY) -m src.pipeline --scale full --out data/full

validate:            ## re-run pipeline for SCALE and print the validation summary
	$(PY) -m src.pipeline --scale $(SCALE) --out data/$(SCALE) && cat data/$(SCALE)/validation_summary.md | head -60

test:
	$(PY) tests/run_all.py

reproduce:           ## run twice, compare row counts + SHA-256 of every output file
	$(PY) -m src.reproduce --scale $(SCALE)

zip:
	$(PY) scripts/package_zip.py

clean:
	rm -rf data/full data/small data/tiny
